"""Stage 4: scene descriptions -> scene_1..N.png.

Adapters (scenes_adapter.primary picks the first; the rest chain as fallbacks,
always producing a FULL set so the pipeline never blocks):

  1. "grok" (default, fal.ai Grok Imagine) with a CONTINUITY PROTOCOL so every
     scene shares one cast / palette / style:
       * scene_1: text-to-image (xai/grok-imagine-image) from the scene prompt
         + episode "visual_bible" + style keywords. Its raw output is kept as
         scenes/grok_anchor.png (the style+cast anchor).
       * scenes 2..N: the EDIT endpoint (xai/grok-imagine-image/edit) with
         reference images = [scene_1 anchor, mascot sprite IF the mascot
         appears in that scene] and a "same style, same characters, same
         palette as the reference" prompt + description + visual_bible.
     Cost-guarded by scenes_adapter.max_usd_per_episode.
  2. "codex" CLI image generation (READ-ONLY sandbox; parses the printed PNG
     path or falls back to the newest PNG created since the call started).
  3. Pillow placeholder (retro background + big pixel text) for every scene
     nothing else could produce.

Every image is then run through pixelate.py for one uniform pixel grid.

Standalone:  python scenes.py --episode ../episodes/ep001-shortest-war
Via run.py:  render_scenes(episode_dir, config)
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import time
from pathlib import Path

from common import EpisodePaths, PROJECT_DIR, get_env, load_config, log, read_json
from pixelate import pixelate_file

CODEX_IMAGE_DIR = Path.home() / ".codex" / "generated_images"
GENERATED_RE = re.compile(r"Generated file:.*?\((/[^)]+\.png)\)", re.IGNORECASE)
ANY_PNG_RE = re.compile(r"(/[^\s)]+\.png)")

MASCOT_HINT_RE = re.compile(r"\b(mascot|character)\b", re.IGNORECASE)

RETRO_BG = [
    (34, 32, 52), (63, 40, 50), (25, 60, 62), (48, 33, 68),
    (72, 60, 30), (30, 50, 80), (60, 30, 45), (40, 55, 40),
]

ANCHOR_NAME = "grok_anchor.png"


def _scene_prompt(scene: str, config: dict) -> str:
    return config["style"]["scene_prompt_template"].format(
        scene=scene, style=config["style"]["keywords"]
    )


def _visual_bible(episode: dict) -> str:
    """Optional episode.json field pinning recurring visuals (uniform colors,
    location, palette) so every scene prompt repeats the same canon."""
    bible = episode.get("visual_bible")
    return bible.strip() if isinstance(bible, str) else ""


# --------------------------------------------------------------------------- #
# Grok adapter (primary): continuity-chained scene set
# --------------------------------------------------------------------------- #
def _grok_settings(adapter: dict) -> dict:
    import grok_image

    return {
        "t2i_model": str(adapter.get("grok_t2i_model", grok_image.GROK_T2I_MODEL)),
        "edit_model": str(adapter.get("grok_edit_model", grok_image.GROK_EDIT_MODEL)),
        "usd_t2i": float(adapter.get("grok_usd_per_t2i", grok_image.USD_PER_T2I)),
        "usd_edit": float(adapter.get("grok_usd_per_edit", grok_image.USD_PER_EDIT)),
        "resolution": str(adapter.get("grok_resolution", "1k")),
        "poll_timeout": int(adapter.get("grok_poll_timeout_seconds", 240)),
        "max_usd": float(adapter.get("max_usd_per_episode", 0.30)),
    }


def _anchor_prompt(scene: str, bible: str, config: dict) -> str:
    base = _scene_prompt(scene, config)
    return f"{base}. {bible}" if bible else base


def _chained_prompt(scene: str, bible: str, config: dict) -> str:
    style = config["style"]["keywords"]
    parts = [
        "Same art style, same characters, same color palette as the reference image.",
        f"{scene.strip().rstrip('.')}.",
    ]
    if bible:
        parts.append(f"{bible.rstrip('.')}.")
    parts.append(f"{style}. no text, no words, no letters, no watermark, "
                 "wide cinematic composition, vertical 9:16 framing")
    return " ".join(parts)


def _mascot_sprite() -> Path | None:
    mascot_dir = PROJECT_DIR / "assets" / "mascot"
    for name in ("mascot.png", "character.png", "raccoon-test.png", "raccoon.png"):
        candidate = mascot_dir / name
        if candidate.exists():
            return candidate
    return None


def _anchor_upload_source(paths: EpisodePaths) -> Path | None:
    """Best local file to upload as the style+cast anchor when scene_1 was not
    generated in this run: the kept raw grok anchor, else the (pixelated)
    scene_1.png."""
    anchor = paths.scenes_dir / ANCHOR_NAME
    if anchor.exists():
        return anchor
    scene_1 = paths.scenes_dir / "scene_1.png"
    return scene_1 if scene_1.exists() else None


def _grok_scene_set(
    scenes: list[str],
    missing: list[int],
    paths: EpisodePaths,
    episode: dict,
    config: dict,
) -> dict[int, Path]:
    """Generate raw PNGs for the missing scene indices (0-based) with the
    continuity chain. Returns {index: raw_path} for every scene that succeeded.
    Raises nothing fatal: per-scene errors are logged and that scene is simply
    absent from the result (codex/placeholder pick it up)."""
    import grok_image

    settings = _grok_settings(config["scenes_adapter"])
    bible = _visual_bible(episode)
    produced: dict[int, Path] = {}
    spent = 0.0

    def within_budget(cost: float) -> bool:
        if spent + cost > settings["max_usd"] + 1e-9:
            log("scenes", f"!!! COST GUARD: ${spent:.3f} spent + ${cost:.3f} would exceed "
                          f"${settings['max_usd']:.2f} scenes budget -> falling back for the rest")
            return False
        return True

    # --- Anchor (scene_1): text-to-image, raw kept for future chained edits.
    anchor_url: str | None = None
    if 0 in missing:
        if not within_budget(settings["usd_t2i"]):
            return produced
        raw = paths.scenes_dir / "scene_1_raw.png"
        try:
            anchor_url = grok_image.text_to_image(
                _anchor_prompt(scenes[0], bible, config), raw,
                model=settings["t2i_model"], aspect_ratio="9:16",
                resolution=settings["resolution"], poll_timeout=settings["poll_timeout"],
            )
            spent += settings["usd_t2i"]
            shutil.copyfile(raw, paths.scenes_dir / ANCHOR_NAME)
            produced[0] = raw
            log("scenes", f"scene_1 anchor generated via grok t2i (${spent:.3f} spent)")
        except Exception as error:  # noqa: BLE001 - scene falls to codex/placeholder
            log("scenes", f"grok t2i failed for scene_1 ({error})")
            return produced  # without an anchor the chain cannot continue

    if anchor_url is None:
        source = _anchor_upload_source(paths)
        if source is None:
            log("scenes", "no scene_1 anchor available -> grok chain skipped")
            return produced
        try:
            anchor_url = grok_image.upload_image(source)
            log("scenes", f"anchor uploaded from {source.name}")
        except Exception as error:  # noqa: BLE001
            log("scenes", f"anchor upload failed ({error}) -> grok chain skipped")
            return produced

    # --- Mascot reference, uploaded lazily only if some scene mentions it.
    mascot_url: str | None = None

    def mascot_reference() -> str | None:
        nonlocal mascot_url
        if mascot_url is not None:
            return mascot_url
        sprite = _mascot_sprite()
        if sprite is None:
            return None
        try:
            mascot_url = grok_image.upload_image(sprite)
        except Exception as error:  # noqa: BLE001
            log("scenes", f"mascot reference upload failed ({error}); continuing without it")
        return mascot_url

    # --- Scenes 2..N: edit endpoint chained on the anchor.
    for index in missing:
        if index == 0:
            continue
        if not within_budget(settings["usd_edit"]):
            break
        references = [anchor_url]
        if MASCOT_HINT_RE.search(scenes[index]):
            reference = mascot_reference()
            if reference is not None:
                references.append(reference)
        raw = paths.scenes_dir / f"scene_{index + 1}_raw.png"
        try:
            grok_image.edit_image(
                _chained_prompt(scenes[index], bible, config), references, raw,
                model=settings["edit_model"], aspect_ratio="9:16",
                resolution=settings["resolution"], poll_timeout=settings["poll_timeout"],
            )
            spent += settings["usd_edit"]
            produced[index] = raw
            log("scenes", f"scene_{index + 1} chained via grok edit "
                          f"({len(references)} ref(s), ${spent:.3f} spent)")
        except Exception as error:  # noqa: BLE001 - scene falls to codex/placeholder
            log("scenes", f"grok edit failed for scene_{index + 1} ({error})")

    log("scenes", f"grok adapter: {len(produced)}/{len(missing)} scenes, ~${spent:.3f}")
    return produced


# --------------------------------------------------------------------------- #
# Codex adapter (fallback)
# --------------------------------------------------------------------------- #
def _find_generated_png(stdout: str, since: float) -> Path | None:
    match = GENERATED_RE.search(stdout) or ANY_PNG_RE.search(stdout)
    if match:
        candidate = Path(match.group(1))
        if candidate.exists():
            return candidate
    if CODEX_IMAGE_DIR.exists():
        fresh = [
            p for p in CODEX_IMAGE_DIR.rglob("*.png")
            if p.stat().st_mtime >= since - 1
        ]
        if fresh:
            return max(fresh, key=lambda p: p.stat().st_mtime)
    return None


def _codex_scene(scene: str, dst_raw: Path, config: dict, timeout: int) -> bool:
    adapter = config["scenes_adapter"]
    codex_bin = adapter["codex_bin"]
    if not Path(codex_bin).exists():
        return False
    prompt = (
        "Generate a single vertical 9:16 image (1080x1920) and save it as scene.png. "
        "The image must be: " + _scene_prompt(scene, config) +
        ". Output only the image file."
    )
    started = time.time()
    try:
        result = subprocess.run(
            [codex_bin, "exec", "-C", str(dst_raw.parent),
             "--sandbox", "workspace-write", "--skip-git-repo-check", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log("scenes", f"codex timed out after {timeout}s for scene")
        return False
    except Exception as error:  # noqa: BLE001
        log("scenes", f"codex invocation error ({error})")
        return False

    generated = _find_generated_png((result.stdout or "") + (result.stderr or ""), started)
    if generated is None:
        log("scenes", "codex produced no locatable PNG; falling back")
        return False
    shutil.copyfile(generated, dst_raw)
    log("scenes", f"codex image copied from {generated}")
    # If codex wrote into our workspace (workspace-write sandbox), clean it up so
    # a later scene's freshness check does not pick up a stale file.
    if generated.resolve() != dst_raw.resolve() and generated.parent.resolve() == dst_raw.parent.resolve():
        generated.unlink(missing_ok=True)
    return True


# --------------------------------------------------------------------------- #
# Placeholder adapter (final fallback)
# --------------------------------------------------------------------------- #
def _load_font(size: int):
    from PIL import ImageFont

    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _shorten(scene: str, max_words: int = 14) -> str:
    words = scene.replace("\n", " ").split()
    text = " ".join(words[:max_words])
    return text + ("..." if len(words) > max_words else "")


def _placeholder_scene(scene: str, dst_raw: Path, index: int, config: dict) -> None:
    """Retro 'title card' fallback. Text lives in the UPPER area so the karaoke
    captions (bottom third) never collide with it."""
    from PIL import Image, ImageDraw

    width = config["video"]["width"]
    height = config["video"]["height"]
    bg = RETRO_BG[index % len(RETRO_BG)]
    accent = RETRO_BG[(index + 3) % len(RETRO_BG)]
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)

    # Chunky border frame for a retro card look.
    for offset, color in ((36, accent), (52, (255, 225, 77))):
        draw.rectangle([offset, offset, width - offset, height - offset], outline=color, width=8)

    label_font = _load_font(60)
    tag = f"SCENE {index + 1}"
    tag_w = draw.textlength(tag, font=label_font)
    draw.text(((width - tag_w) // 2, 150), tag, font=label_font, fill=(255, 225, 77))

    font = _load_font(64)
    margin = 130
    lines = _wrap(draw, _shorten(scene), font, width - 2 * margin)
    line_height = 84
    block_height = line_height * len(lines)
    # Center the block in the UPPER 55% of the frame.
    y = int(height * 0.30) - block_height // 2
    for line in lines:
        text_w = draw.textlength(line, font=font)
        x = (width - text_w) // 2
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(238, 238, 238))
        y += line_height

    image.save(dst_raw)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _grok_available(config: dict) -> bool:
    if str(config["scenes_adapter"].get("primary", "grok")).lower() != "grok":
        return False
    if not get_env("FAL_KEY"):
        log("scenes", "!!! FAL_KEY not set (pipeline/.env) -> grok adapter unavailable")
        return False
    try:
        import fal_client  # noqa: F401
    except Exception as error:  # noqa: BLE001
        log("scenes", f"!!! fal_client unavailable ({error}) -> grok adapter unavailable")
        return False
    return True


def render_scenes(episode_dir: Path, config: dict, force: bool = False) -> list[Path]:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    episode = read_json(paths.episode_json)
    scenes = episode["scenes"]

    adapter = config["scenes_adapter"]
    primary = str(adapter.get("primary", "grok")).lower()
    pix = config["pixelate"]
    codex_budget = int(adapter.get("codex_scene_budget", 0))
    total_timeout = int(adapter.get("codex_total_timeout_seconds", 0))
    deadline = time.time() + total_timeout
    codex_used = 0
    origins: dict[int, str] = {}

    missing = [
        index for index in range(len(scenes))
        if force or not (paths.scenes_dir / f"scene_{index + 1}.png").exists()
    ]
    for index in range(len(scenes)):
        if index not in missing:
            log("scenes", f"scene_{index + 1}.png exists, skipping")

    grok_raws: dict[int, Path] = {}
    if missing and _grok_available(config):
        grok_raws = _grok_scene_set(scenes, missing, paths, episode, config)
    elif missing and primary == "placeholder":
        codex_budget = 0  # explicit placeholder mode also skips codex

    outputs: list[Path] = []
    for index, scene in enumerate(scenes):
        final = paths.scenes_dir / f"scene_{index + 1}.png"
        if index not in missing:
            outputs.append(final)
            continue

        raw = paths.scenes_dir / f"scene_{index + 1}_raw.png"
        origin = "placeholder"
        if index in grok_raws:
            origin = "grok"
        else:
            remaining = int(deadline - time.time())
            if codex_used < codex_budget and remaining > 30:
                if _codex_scene(scene, raw, config, timeout=remaining):
                    codex_used += 1
                    origin = "codex"
            if origin == "placeholder":
                _placeholder_scene(scene, raw, index, config)

        pixelate_file(raw, final, pix["downscale_width"], pix["palette_colors"])
        raw.unlink(missing_ok=True)
        origins[index] = origin
        log("scenes", f"scene_{index + 1}.png ready (origin={origin})")
        outputs.append(final)

    if missing:
        summary = ", ".join(f"scene_{i + 1}={origins.get(i, 'cached')}" for i in missing)
        log("scenes", f"{len(outputs)} scenes ready ({summary})")
    else:
        log("scenes", f"{len(outputs)} scenes ready (all cached)")
    return outputs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render scene images (grok continuity chain + codex + placeholder + pixelate)"
    )
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="re-render even if scene PNGs exist")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    render_scenes(Path(args.episode), load_config(), force=args.force)


if __name__ == "__main__":
    main()
