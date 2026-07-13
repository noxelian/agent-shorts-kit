"""Production episode builder: reads episodes/<slug>/bits.json.

Replaces the per-episode build_bits_ep0NN.py clones (ep021/ep022 keep theirs).

    ./.venv/bin/python build_bits2.py <slug> board [--res 1K]
    ./.venv/bin/python build_bits2.py <slug> approve
    ./.venv/bin/python build_bits2.py <slug> gen [--res 1K] [--only 1,3]
    ./.venv/bin/python build_bits2.py <slug> install
    ./.venv/bin/python build_bits2.py <slug> hero              # fal Vidu Q2 Pro ($0.35)
    ./.venv/bin/python build_bits2.py <slug> animate [--limit N] [--max-usd 3]
                                                               # ALL scenes via WaveSpeed
                                                               # Vidu Q2 Pro Fast (~$0.08)

Workflow: board creates one labelled contact sheet with every planned scene.
Review it, then run approve. Image generation is blocked until the approval
marker matches the latest board.

gen defaults to 1K (nb2 $0.08/img; the 512/128 pixelate pass erases the 2K gain).
Refs go as data URIs (fal storage 403s for this key). Resumable everywhere: existing
bit_NN.png / scene_N_video.mp4 are skipped. animate needs WAVESPEED_API_KEY in .env.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixelate import pixelate_image  # noqa: E402
from common import get_env, load_env  # noqa: E402
from PIL import Image  # noqa: E402
import requests  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = Path(__file__).resolve().parent
PRODUCTION = json.loads((PIPELINE / "production.json").read_text(encoding="utf-8"))
VAL = ROOT / ".work"
VAL.mkdir(exist_ok=True)
NB2 = "fal-ai/nano-banana-2/edit"
VIDU_FAL = "fal-ai/vidu/q2/image-to-video/pro"
STYLE = PRODUCTION["style"]
REF_RULE = PRODUCTION["reference_rule"]
BAN = PRODUCTION["negative"]

WS_BASE = "https://api.wavespeed.ai/api/v3"
WS_MODEL_PATH = "vidu/q2-pro/image-to-video-fast"  # verify path/price on first call
WS_USD_PER_CLIP = 0.08

REFS = [(ROOT / path).resolve() for path in PRODUCTION.get("reference_images", [])]

I2V_PREFIX = "Fast-paced pixel-art historical storytelling animation, 16-bit retro game style. "
I2V_SUFFIX = (
    " Full 2D character and object animation, not just camera movement: expressive "
    "poses, clear action, moving props, cloth, nets, paper, light, and crowd energy. "
    "Preserve the still's composition, characters, uniforms, and sharp pixel edges. "
    "No morphing, no duplicate characters, no extra balls, no melted faces, no new text."
)


def _data_uri(path: Path, max_side: int = 1024, quality: int = 88) -> str:
    """fal storage upload 403s for this key -> inline refs as data URIs."""
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _available_refs() -> list[Path]:
    missing = [path for path in REFS if not path.exists()]
    if missing:
        joined = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(
            "Configured reference images are missing:\n" + joined +
            "\nUpdate pipeline/production.json or add the files."
        )
    return list(REFS)


def _run(model: str, arguments: dict, timeout: int = 420) -> dict:
    import fal_client
    from fal_client import Completed

    handle = fal_client.submit(model, arguments=arguments)
    print(f"  submitted {model} req={handle.request_id}")
    deadline = time.time() + timeout
    while True:
        status = handle.status()
        if isinstance(status, Completed):
            return handle.get()
        if time.time() > deadline:
            raise TimeoutError(f"{model} req {handle.request_id} exceeded {timeout}s")
        time.sleep(3)


def _download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with dst.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if chunk:
                    handle.write(chunk)
    print(f"  saved {dst} ({dst.stat().st_size // 1024} KB)")


def _first_image_url(result: dict) -> str:
    images = result.get("images") or []
    if images and isinstance(images[0], dict) and images[0].get("url"):
        return images[0]["url"]
    raise RuntimeError(f"no image url in result: {str(result)[:400]}")


class Episode:
    def __init__(self, slug: str) -> None:
        self.dir = ROOT / "episodes" / slug
        spec_path = self.dir / "bits.json"
        if not spec_path.exists():
            raise FileNotFoundError(f"{spec_path} — write the bit breakdown first")
        self.spec = json.loads(spec_path.read_text())
        self.bits = self.spec["bits"]
        self.world = self.spec["world"]
        if not isinstance(self.world, str) or not self.world.strip():
            raise ValueError("bits.json 'world' must be a non-empty string")
        if not isinstance(self.bits, list) or not self.bits:
            raise ValueError("bits.json 'bits' must be a non-empty array")
        expected = list(range(1, len(self.bits) + 1))
        actual = [item.get("n") for item in self.bits if isinstance(item, dict)]
        if actual != expected:
            raise ValueError(f"bits.json scene numbers must be sequential 1..{len(self.bits)}")
        for item in self.bits:
            if not str(item.get("vo", "")).strip() or not str(item.get("desc", "")).strip():
                raise ValueError(f"bit {item.get('n')} needs non-empty 'vo' and 'desc'")
        bits_dirname = (self.spec.get("meta") or {}).get("bits_dirname") or "generated"
        self.bits_dir = self.dir / bits_dirname
        self.bits_dir.mkdir(exist_ok=True)
        self.storyboard_dir = self.dir / "storyboard"

    def bit_png(self, n: int) -> Path:
        return self.bits_dir / f"bit_{n:02d}.png"

    @property
    def board_raw(self) -> Path:
        return self.storyboard_dir / "board_raw.png"

    @property
    def board_contact_sheet(self) -> Path:
        return self.storyboard_dir / "contact-sheet.png"

    @property
    def board_approval(self) -> Path:
        return self.storyboard_dir / "approved.json"


# ---------------------------------------------------------------- storyboard / approval

def _board_grid(count: int) -> tuple[int, int]:
    """Return a compact landscape grid that keeps every story beat visible."""
    if count <= 12:
        return 4, 3
    if count <= 16:
        return 4, 4
    if count <= 20:
        return 5, 4
    if count <= 30:
        return 5, 6
    return 6, (count + 5) // 6


def _board_prompt(ep: Episode) -> str:
    columns, rows = _board_grid(len(ep.bits))
    beats = "\n".join(f"Panel {bit['n']:02d}: {bit['desc']}" for bit in ep.bits)
    return (
        "Create ONE polished landscape 16:9 director's storyboard contact sheet for "
        "a vertical 9:16 pixel-art YouTube Short. Use a strict "
        f"{columns}-column by {rows}-row grid with one distinct illustration in every "
        "panel and thin dark gutters. The panels are visual planning frames, not a comic "
        "page: keep the same recurring character, palette, location continuity and "
        "cinematic lighting across the sheet. No captions, speech bubbles, panel numbers, "
        "logos, watermarks, or readable text; layout markers will be added separately. "
        f"Story world: {ep.world}\n\nExact panel plan:\n{beats}"
    )


def _write_board_manifest(ep: Episode) -> None:
    lines = [f"# Storyboard — {ep.dir.name}", "",
             "Approve only when every numbered scene is on-model and tells the intended story.", ""]
    for bit in ep.bits:
        lines.extend((f"## {bit['n']:02d}", f"Voice: {bit['vo']}",
                      f"Visual: {bit['desc']}", ""))
    (ep.storyboard_dir / "manifest.md").write_text("\n".join(lines), encoding="utf-8")


def _label_board(ep: Episode) -> None:
    """Add reliable scene numbers after generation; image models cannot number grids."""
    from PIL import ImageDraw, ImageFont

    image = Image.open(ep.board_raw).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                                  max(20, image.width // 42))
    except OSError:
        font = ImageFont.load_default()
    cols, rows = _board_grid(len(ep.bits))
    cell_w, cell_h = image.width / cols, image.height / rows
    for index, bit in enumerate(ep.bits):
        col, row = index % cols, index // cols
        x, y = int(col * cell_w + 12), int(row * cell_h + 12)
        label = f"{bit['n']:02d}"
        bbox = draw.textbbox((x, y), label, font=font)
        draw.rounded_rectangle((x - 8, y - 6, bbox[2] + 8, bbox[3] + 6), radius=8,
                               fill=(10, 18, 30), outline=(255, 220, 70), width=3)
        draw.text((x, y), label, font=font, fill=(255, 235, 100))
    image.save(ep.board_contact_sheet)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_board(ep: Episode, res: str, provider: str, force: bool) -> None:
    if ep.board_raw.exists() and not force:
        raise SystemExit(f"Storyboard already exists: {ep.board_contact_sheet}. Review it or pass --force to replace it.")
    ep.storyboard_dir.mkdir(exist_ok=True)
    ep.board_approval.unlink(missing_ok=True)
    prompt = _board_prompt(ep)
    (ep.storyboard_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    _write_board_manifest(ep)
    print(f"Generating one {len(ep.bits)}-scene storyboard via {provider} -> {ep.board_raw}")
    refs = _available_refs()
    if provider in {"vertex", "gemini"}:
        _google_generate_image(prompt, refs, ep.board_raw, provider, aspect_ratio="16:9")
    else:
        result = _run(NB2, {"prompt": prompt, "image_urls": [_data_uri(p) for p in refs],
                            "resolution": res, "aspect_ratio": "16:9", "num_images": 1,
                            "output_format": "png"})
        _download(_first_image_url(result), ep.board_raw)
    _label_board(ep)
    print("REVIEW REQUIRED:", ep.board_contact_sheet)
    print("After human approval run: build_bits2.py", ep.dir.name, "approve")


def cmd_approve(ep: Episode) -> None:
    if not ep.board_raw.exists() or not ep.board_contact_sheet.exists():
        raise SystemExit("No storyboard found. Run board first.")
    payload = {"approved_at": datetime.now(timezone.utc).isoformat(),
               "board_raw_sha256": _sha256(ep.board_raw), "scene_count": len(ep.bits)}
    ep.board_approval.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("APPROVED:", ep.board_contact_sheet)


def _require_approved_board(ep: Episode) -> None:
    if not ep.board_raw.exists() or not ep.board_contact_sheet.exists():
        raise SystemExit("Generation blocked: run board and review the contact sheet first.")
    if not ep.board_approval.exists():
        raise SystemExit(f"Generation blocked: approve {ep.board_contact_sheet} first.")
    approval = json.loads(ep.board_approval.read_text(encoding="utf-8"))
    if approval.get("board_raw_sha256") != _sha256(ep.board_raw):
        raise SystemExit("Generation blocked: storyboard changed after approval; review and approve it again.")
    if approval.get("scene_count") != len(ep.bits):
        raise SystemExit("Generation blocked: scene count changed after approval; regenerate and approve the board.")


# ---------------------------------------------------------------- gen

def _vertex_settings() -> tuple[str, str, str, str]:
    vertex = PRODUCTION.get("vertex", {})
    project = get_env("GOOGLE_CLOUD_PROJECT") or str(vertex.get("project", "")).strip()
    account = get_env("GOOGLE_CLOUD_ACCOUNT") or str(vertex.get("account", "")).strip()
    image_location = str(vertex.get("image_location", "global"))
    video_location = str(vertex.get("video_location", "us-central1"))
    if not project:
        raise RuntimeError("Vertex provider needs GOOGLE_CLOUD_PROJECT in pipeline/.env")
    return project, account, image_location, video_location


def _gcloud_token() -> str:
    _project, account, _image_location, _video_location = _vertex_settings()
    command = ["gcloud", "auth", "print-access-token"]
    if account:
        command.append(f"--account={account}")
    result = subprocess.run(command,
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _google_parts(prompt: str, ref_paths: list[Path]) -> list[dict]:
    parts: list[dict] = []
    for path in ref_paths:
        img = Image.open(path).convert("RGB")
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        parts.append({"inlineData": {"mimeType": "image/jpeg",
                                     "data": base64.b64encode(buf.getvalue()).decode()}})
    parts.append({"text": prompt})
    return parts


def _save_google_image(data: dict, dst: Path, provider: str) -> None:
    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(base64.b64decode(part["inlineData"]["data"]))
            print(f"  saved {dst.name} ({dst.stat().st_size // 1024} KB, {provider})")
            return
    raise RuntimeError(f"{provider} returned no image: {str(data)[:300]}")


def _google_generate_image(prompt: str, ref_paths: list[Path], dst: Path,
                           provider: str, aspect_ratio: str = "9:16") -> None:
    """Generate with Gemini 3.1 Flash Image via API key or Vertex gcloud auth."""
    model = str(PRODUCTION.get("image_model", "gemini-3.1-flash-image"))
    body = {
        "contents": [{"role": "user", "parts": _google_parts(prompt, ref_paths)}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }
    if provider == "gemini":
        key = get_env("GEMINI_API_KEY") or get_env("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("Gemini provider needs GEMINI_API_KEY in pipeline/.env")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": key}
    elif provider == "vertex":
        project, _account, image_location, _video_location = _vertex_settings()
        url = (f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/"
               f"{image_location}/publishers/google/models/{model}:generateContent")
        headers = {"Authorization": f"Bearer {_gcloud_token()}"}
    else:
        raise ValueError(f"unsupported Google image provider: {provider}")
    data = None
    for attempt in range(6):
        if provider == "vertex":
            headers["Authorization"] = f"Bearer {_gcloud_token()}"
        response = requests.post(url, json=body, timeout=300, headers=headers)
        data = response.json()
        error = data.get("error")
        if not error:
            break
        if error.get("code") == 429:  # per-minute quota on fresh projects
            wait = 30 * (attempt + 1)
            print(f"  429 quota, retry in {wait}s (attempt {attempt + 1}/6)")
            time.sleep(wait)
            continue
        raise RuntimeError(f"{provider} image error: {str(error)[:300]}")
    else:
        raise RuntimeError(f"{provider} image error after retries: {str(data)[:200]}")
    _save_google_image(data, dst, provider)


def _gen_image(prompt_desc: str, world: str, dst: Path, refs: list, res: str,
               provider: str = "fal") -> None:
    if dst.exists():
        print(f"  SKIP (exists): {dst.name}")
        return
    prompt = (f"{REF_RULE} New scene: {prompt_desc} {world} {STYLE}. "
              f"Vertical 9:16 composition. {BAN}")
    if provider in {"vertex", "gemini"}:
        _google_generate_image(prompt, refs, dst, provider)  # refs = Paths
        return
    result = _run(NB2, {"prompt": prompt, "image_urls": refs, "resolution": res,
                        "aspect_ratio": "9:16", "num_images": 1, "output_format": "png"})
    _download(_first_image_url(result), dst)


LOCATION_RULE = (
    " CONTINUITY: the LAST reference image shows this exact location earlier in the "
    "same story. Copy its environment, architecture, ground surface, vegetation, "
    "lighting, time of day and color palette EXACTLY - this is the same place minutes "
    "later. Change ONLY the action and camera framing described above."
)


def _location_anchors(ep: Episode) -> dict[str, Path]:
    """Anchor image per location: the bit flagged location_anchor, else the first
    bit of that location (story order). Only anchors that already exist on disk
    count - gen creates them on the fly as it walks the bit list."""
    anchors: dict[str, Path] = {}
    flagged = {b["location"]: b["n"] for b in ep.bits
               if b.get("location") and b.get("location_anchor")}
    for bit in ep.bits:
        loc = bit.get("location")
        if not loc or loc in anchors:
            continue
        n = flagged.get(loc, bit["n"])
        path = ep.bit_png(n)
        if path.exists():
            anchors[loc] = path
    return anchors


def cmd_gen(ep: Episode, res: str, only: set[int] | None, provider: str = "fal") -> None:
    pending = [bit for bit in ep.bits if (not only or bit["n"] in only)
               and not ep.bit_png(bit["n"]).exists()]
    if not pending:
        print("No missing approved scene images to generate.")
        return
    _require_approved_board(ep)
    refs = _available_refs()
    base_refs = refs if provider in {"vertex", "gemini"} else [_data_uri(p) for p in refs]
    print(f"gen @{res} via {provider}: {len(ep.bits)} bits -> {ep.bits_dir}")
    failed: list[int] = []
    for bit in ep.bits:
        if only and bit["n"] not in only:
            continue
        print(f"-- bit {bit['n']}: {bit['vo'][:48]}")
        try:
            world = bit.get("world") or ep.world
            anchors = _location_anchors(ep)
            loc = bit.get("location")
            anchor = anchors.get(loc) if loc else None
            desc = bit["desc"]
            bit_refs = base_refs
            if anchor is not None and anchor != ep.bit_png(bit["n"]):
                extra = anchor if provider in {"vertex", "gemini"} else _data_uri(anchor)
                bit_refs = [*base_refs, extra]
                desc = bit["desc"] + LOCATION_RULE
                print(f"   location '{loc}' anchored to {anchor.name}")
            _gen_image(desc, world, ep.bit_png(bit["n"]), bit_refs, res, provider)
        except Exception as error:  # noqa: BLE001 - keep the batch going
            failed.append(bit["n"])
            print(f"  !! bit {bit['n']} failed: {error}")
    if only is None and ep.spec.get("thumb_desc"):
        print("-- thumb portrait")
        try:
            _gen_image(ep.spec["thumb_desc"], ep.world, ep.bits_dir / "bit_thumb.png",
                       base_refs, res, provider)
        except Exception as error:  # noqa: BLE001
            print(f"  !! thumb failed: {error}")
    print(f"gen done, failed: {failed or 'none'} (re-run to retry)")


# ---------------------------------------------------------------- install

def _finish(img: Image.Image) -> Image.Image:
    w, h = img.size
    crop_h = round(w / (1080 / 1920))
    top = (h - crop_h) // 2
    img = img.crop((0, top, w, top + crop_h)).resize((1080, 1920), Image.LANCZOS)
    return pixelate_image(img, 512, 128)


def cmd_install(ep: Episode) -> None:
    scenes_dir = ep.dir / "scenes"
    backup = ep.dir / "scenes_legacy_backup"
    if scenes_dir.exists() and any(scenes_dir.iterdir()) and not backup.exists():
        scenes_dir.rename(backup)
        print("backed up ->", backup.name)
    scenes_dir.mkdir(exist_ok=True)
    (ep.dir / "out").mkdir(exist_ok=True)
    for stale in list(scenes_dir.glob("scene_*.png")) + list(scenes_dir.glob("scene_*_video.mp4")):
        stale.unlink()
    print("cleared stale scene stills/videos")

    for bit in ep.bits:
        src = ep.bit_png(bit["n"])
        if not src.exists():
            raise FileNotFoundError(f"{src} — run gen first")
        _finish(Image.open(src).convert("RGB")).save(scenes_dir / f"scene_{bit['n']}.png")
    print(f"installed {len(ep.bits)} stills")

    thumb_src = ep.bits_dir / "bit_thumb.png"
    if thumb_src.exists():
        thumb = _finish(Image.open(thumb_src).convert("RGB"))
        thumb.save(ep.dir / "out/thumb_portrait_base.png")
        thumb.save(ep.dir / "out/thumb_portrait_base_raw.png")
        print("thumb portrait installed")

    episode_json = ep.dir / "episode.json"
    episode = json.loads(episode_json.read_text())
    legacy = ep.dir / "episode_legacy_backup.json"
    if not legacy.exists():
        shutil.copyfile(episode_json, legacy)
    episode["scene_count"] = len(ep.bits)
    episode["scenes"] = [b["desc"] for b in ep.bits]
    episode["timeline"] = [{"scene": b["n"], "vo": b["vo"], "visual": b["desc"][:80]}
                           for b in ep.bits]
    episode.pop("hero_mode", None)
    for key in ("title", "narration", "word_count", "callouts", "narration_tagged",
                "description", "tags", "hashtags", "thumbnail_word", "emphasis"):
        if ep.spec.get(key) is not None:
            episode[key] = ep.spec[key]
    if ep.spec.get("hero_scene"):
        episode["hero_scene"] = ep.spec["hero_scene"]
    episode_json.write_text(json.dumps(episode, ensure_ascii=False, indent=2))
    print("episode.json updated: scene_count", len(ep.bits))

    for name in ("voice.mp3", "voice.prefx.mp3", "words.json", "voice.el.raw.json",
                 "voice.cues.json", "voice.edge.mp3"):
        (ep.dir / name).unlink(missing_ok=True)
    for name in ("final.mp4", "thumb_vertical.png", "thumb_wide.png", "props.json"):
        (ep.dir / "out" / name).unlink(missing_ok=True)
    print("voice/render artefacts cleaned (voice re-gen on next run.py)")


# ---------------------------------------------------------------- shared video encode

def _encode_locked(raw: Path, still: Path, dst: Path, tag: str) -> None:
    """Re-pixelate every frame against the still's 128-color palette -> no boiling."""
    palette_ref = Image.open(still).convert("RGB").quantize(colors=128, method=Image.MEDIANCUT)
    frames = VAL / f"frames_{tag}"
    pixeled = VAL / f"framespx_{tag}"
    for d in (frames, pixeled):
        d.mkdir(exist_ok=True)
        for f in d.glob("*.png"):
            f.unlink()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                    "-vf", "scale=1080:1936:flags=lanczos,crop=1080:1920:0:8",
                    str(frames / "f%04d.png")], check=True)
    for fp in sorted(frames.glob("*.png")):
        img = Image.open(fp).convert("RGB")
        small = img.resize((512, round(1920 * 512 / 1080)), Image.NEAREST)
        small.quantize(palette=palette_ref, dither=Image.NONE).convert("RGB").resize(
            (1080, 1920), Image.NEAREST).save(pixeled / fp.name)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24",
                    "-i", str(pixeled / "f%04d.png"),
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(dst)], check=True)
    for f in list(frames.glob("*.png")) + list(pixeled.glob("*.png")):
        f.unlink()


def _motion_prompt(bit: dict) -> str:
    motion = bit.get("motion") or "gentle ambient sway, soft light flicker"
    return I2V_PREFIX + motion + I2V_SUFFIX


# ---------------------------------------------------------------- hero (fal, $0.35)

def cmd_hero(ep: Episode) -> None:
    n = int(ep.spec.get("hero_scene") or 0)
    if not n:
        raise SystemExit("bits.json has no hero_scene")
    dst = ep.dir / f"scenes/scene_{n}_video.mp4"
    if dst.exists():
        print("SKIP (exists):", dst)
        return
    still = ep.dir / f"scenes/scene_{n}.png"
    bit = next(b for b in ep.bits if b["n"] == n)
    result = _run(VIDU_FAL, {
        "prompt": _motion_prompt(bit),
        "image_url": _data_uri(still, max_side=2048, quality=92),
        "resolution": "720p", "duration": 5, "movement_amplitude": "small",
    }, timeout=600)
    url = (result.get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"no video url: {str(result)[:300]}")
    raw = VAL / f"hero_raw_{n}.mp4"
    _download(url, raw)
    _encode_locked(raw, still, dst, f"hero{n}")
    raw.unlink(missing_ok=True)
    print("hero clip installed:", dst)


# ---------------------------------------------------------------- animate (WaveSpeed)

def _ws_headers() -> dict:
    import os
    key = os.environ.get("WAVESPEED_API_KEY", "").strip()
    if not key:
        raise SystemExit("WAVESPEED_API_KEY missing in pipeline/.env — register at "
                         "wavespeed.ai, top up, add the key, then re-run animate")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _ws_generate(still: Path, prompt: str, timeout: int = 600) -> str:
    """Submit one i2v task to WaveSpeed, poll, return the output video URL."""
    import requests

    payload = {
        "image": _data_uri(still, max_side=2048, quality=92),
        "prompt": prompt,
        "duration": 5,
        "resolution": "720p",
        "movement_amplitude": "small",  # ignored by Q2 per Vidu docs; harmless
        "seed": -1,
    }
    response = requests.post(f"{WS_BASE}/{WS_MODEL_PATH}", json=payload,
                             headers=_ws_headers(), timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"WaveSpeed submit {response.status_code}: {response.text[:300]}")
    task_id = (response.json().get("data") or {}).get("id")
    if not task_id:
        raise RuntimeError(f"no task id: {response.text[:300]}")
    print(f"  submitted ws task {task_id}")
    deadline = time.time() + timeout
    while True:
        poll = requests.get(f"{WS_BASE}/predictions/{task_id}/result",
                            headers=_ws_headers(), timeout=60)
        data = poll.json().get("data") or {}
        status = data.get("status")
        if status == "completed":
            outputs = data.get("outputs") or []
            if not outputs:
                raise RuntimeError(f"completed without outputs: {str(data)[:300]}")
            return outputs[0]
        if status == "failed":
            raise RuntimeError(f"ws task failed: {data.get('error')}")
        if time.time() > deadline:
            raise TimeoutError(f"ws task {task_id} exceeded {timeout}s")
        time.sleep(4)


FAL_USD_PER_CLIP = 0.35
VEO_USD_PER_CLIP = 0.9  # 6s x ~$0.15/s fast tier; paid from GCP credits, not cash


def _veo_generate(still: Path, prompt: str, timeout: int = 600) -> bytes:
    """Veo 3.1 Fast i2v on Vertex: submit long-running op, poll, return mp4 bytes."""
    import requests

    project, _account, _image_location, video_location = _vertex_settings()
    video_model = str(PRODUCTION.get("vertex", {}).get(
        "video_model", "veo-3.1-fast-generate-001"
    ))
    veo_base = (f"https://{video_location}-aiplatform.googleapis.com/v1/projects/"
                f"{project}/locations/{video_location}/publishers/google/models/{video_model}")
    img_b64 = base64.b64encode(still.read_bytes()).decode()
    token = _gcloud_token()
    response = requests.post(f"{veo_base}:predictLongRunning",
        headers={"Authorization": f"Bearer {token}"},
        json={"instances": [{"prompt": prompt,
                             "image": {"bytesBase64Encoded": img_b64, "mimeType": "image/png"}}],
              "parameters": {"durationSeconds": 6, "aspectRatio": "9:16",
                             "sampleCount": 1, "resolution": "720p"}},
        timeout=120)
    data = response.json()
    if "name" not in data:
        raise RuntimeError(f"veo submit failed: {str(data)[:300]}")
    op_name = data["name"]
    print(f"  submitted veo op ...{op_name[-24:]}")
    deadline = time.time() + timeout
    while True:
        poll = requests.post(f"{veo_base}:fetchPredictOperation",
                             headers={"Authorization": f"Bearer {_gcloud_token()}"},
                             json={"operationName": op_name}, timeout=60)
        result = poll.json()
        if result.get("done"):
            if "error" in result:
                raise RuntimeError(f"veo op error: {str(result['error'])[:300]}")
            videos = (result.get("response") or {}).get("videos") or []
            if not videos:
                raise RuntimeError(f"veo done without videos: {str(result)[:300]}")
            return base64.b64decode(videos[0]["bytesBase64Encoded"])
        if time.time() > deadline:
            raise TimeoutError(f"veo op exceeded {timeout}s")
        time.sleep(10)


def _fal_generate(still: Path, prompt: str, timeout: int = 600) -> str:
    """Submit one i2v task to fal Vidu Q2 Pro, return the output video URL."""
    result = _run(VIDU_FAL, {
        "prompt": prompt,
        "image_url": _data_uri(still, max_side=2048, quality=92),
        "resolution": "720p", "duration": 5, "movement_amplitude": "small",
    }, timeout=timeout)
    url = (result.get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"no video url: {str(result)[:300]}")
    return url


def cmd_animate(ep: Episode, limit: int | None, max_usd: float, provider: str,
                only: set[int] | None = None) -> None:
    generate = {"ws": _ws_generate, "fal": _fal_generate, "veo": _veo_generate}[provider]
    usd_per_clip = {"ws": WS_USD_PER_CLIP, "fal": FAL_USD_PER_CLIP,
                    "veo": VEO_USD_PER_CLIP}[provider]
    spent = 0.0
    done = 0
    for bit in ep.bits:
        n = bit["n"]
        if only and n not in only:
            continue
        dst = ep.dir / f"scenes/scene_{n}_video.mp4"
        if dst.exists():
            print(f"SKIP scene {n} (exists)")
            continue
        if limit is not None and done >= limit:
            print(f"limit {limit} reached, stopping")
            break
        if spent + usd_per_clip > max_usd + 1e-9:
            print(f"!!! COST GUARD: ${spent:.2f} spent, next clip would exceed ${max_usd:.2f}")
            break
        still = ep.dir / f"scenes/scene_{n}.png"
        if not still.exists():
            print(f"!! scene {n}: still missing, run install first")
            continue
        try:
            output = generate(still, _motion_prompt(bit))
            raw = VAL / f"{provider}_raw_{n}.mp4"
            if isinstance(output, bytes):
                raw.write_bytes(output)
            else:
                _download(output, raw)
            _encode_locked(raw, still, dst, f"{provider}{n}")
            raw.unlink(missing_ok=True)
            spent += usd_per_clip
            done += 1
            print(f"OK scene {n} (~${spent:.2f} total)")
        except Exception as error:  # noqa: BLE001 - keep the batch going
            print(f"!! scene {n}: {type(error).__name__} {str(error)[:200]}")
    total = len(list((ep.dir / "scenes").glob("scene_*_video.mp4")))
    print(f"ANIMATE DONE ({provider}): {total}/{len(ep.bits)} clips, ~${spent:.2f} this run")


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("command", choices=["board", "approve", "gen", "install", "hero", "animate"])
    parser.add_argument("--res", default="1K", help="nb2 resolution for gen (1K|2K)")
    parser.add_argument("--only", help="comma-separated bit numbers for gen")
    parser.add_argument("--limit", type=int, help="max new clips for animate")
    parser.add_argument("--max-usd", type=float, default=3.0, help="animate cost cap")
    parser.add_argument("--provider", default=None,
                        help="board/gen: gemini|vertex|fal (default from production.json). "
                             "animate: ws|fal|veo (default veo, GCP credits)")
    parser.add_argument("--force", action="store_true", help="replace an existing storyboard board")
    args = parser.parse_args()

    load_env()
    ep = Episode(args.slug)
    image_provider = args.provider or str(PRODUCTION.get("image_provider", "gemini"))
    if args.command == "board":
        cmd_board(ep, args.res, image_provider, args.force)
    elif args.command == "approve":
        cmd_approve(ep)
    elif args.command == "gen":
        only = {int(x) for x in args.only.split(",")} if args.only else None
        cmd_gen(ep, args.res, only, image_provider)
    elif args.command == "install":
        cmd_install(ep)
    elif args.command == "hero":
        cmd_hero(ep)
    elif args.command == "animate":
        only = {int(x) for x in args.only.split(",")} if args.only else None
        cmd_animate(ep, args.limit, args.max_usd, args.provider or "veo", only)


if __name__ == "__main__":
    main()
