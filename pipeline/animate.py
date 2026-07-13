"""Stage 4.7: hero-scene image-to-video via fal.ai (Grok Imagine / Wan turbo).

For the episode's hero scene(s) this stage:
  1. uploads the still (scenes/scene_N.png) to fal, submits an image-to-video job,
     polls the queue (per-job deadline), and downloads the raw mp4;
  2. re-pixelates EVERY frame against ONE SHARED palette (the frame-0 palette
     applied to all frames, no dithering) so the grid never "boils" frame to
     frame -- per-frame palettes measured +24% temporal noise in the test;
  3. bakes a seamless forward+reverse BOOMERANG (0..N-1,N-2..1) so a plain
     Remotion <Loop> restarts exactly on a turnaround -> the loop seam is
     mathematically invisible (no hard restart jump);
  4. writes scenes/scene_N_video.mp4 (production-width, fps_out, NO audio).

Hard guarantees:
  * Resumable   - skips a scene whose scene_N_video.mp4 already exists.
  * Cost-capped - refuses beyond config.animate.max_clips_per_episode AND
                  max_usd_per_episode (whichever is tighter).
  * Never blocks- ANY failure (missing dep, submit/poll/timeout, download, or
                  ffmpeg) warns LOUDLY, removes every partial file, and leaves
                  the scene to fall back to stills. The pipeline continues.

Standalone:  python animate.py --episode ../episodes/ep021-usa-beat-england-1950
Via run.py:  animate(episode_dir, config)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from common import EpisodePaths, get_env, load_config, log, read_json
from pixelate import pixelate_image  # shared still-pixelation primitive (reused below)

# x264 CRF for the hero intermediate clip. Kept a little below the final-render
# CRF (23) so hard pixel edges survive Remotion's re-encode without ringing, while
# staying far leaner than a near-lossless master (this file is only a render input).
MP4_CRF = 20

# Motion-potential keyword groups for the hero-scene heuristic. Each maps a set of
# description substrings to an ambient-motion hint phrase (also reused to auto-fill
# hero_motion_hints when the episode did not specify any). Kept here, not in
# config, so the scoring stays a single small self-contained list.
MOTION_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("crowd", "terrace", "stands", "spectator", "audience", "cheer"), "the crowd sways and cheers gently"),
    (("flag", "banner", "pennant"), "flags and banners wave"),
    (("fire", "flame", "torch", "blaze", "ember"), "flames flicker"),
    (("smoke", "smoulder", "smolder"), "smoke drifts"),
    (("sea", "ocean", "wave", "surf", "tide"), "water ripples and waves roll"),
    (("river", "water", "splash"), "water ripples"),
    (("rain", "storm", "downpour"), "rain falls and light flickers"),
    (("battle", "charge", "clash", "melee"), "figures shift and sway"),
    (("wind", "breeze", "gust"), "the wind stirs"),
    (("crash", "explosion", "blast", "cannon", "shell"), "smoke and dust drift"),
    (("dust", "sand"), "dust drifts"),
    (("snow", "blizzard"), "snow falls"),
    (("cloud", "sky"), "clouds drift slowly"),
    (("sun", "sunlight", "sunlit", "glow", "light"), "light flickers softly"),
    (("ball", "juggl", "kick", "pitch", "grass", "field"), "players and grass sway subtly"),
    (("tree", "palm", "leaf", "leaves", "forest"), "leaves rustle"),
    (("torchlight", "candle", "lantern"), "flame-light flickers"),
)


# --------------------------------------------------------------------------- #
# Hero-scene selection + prompt
# --------------------------------------------------------------------------- #
def _motion_score(description: str) -> int:
    """Count distinct motion-keyword groups a scene description matches."""
    text = description.lower()
    return sum(1 for keys, _hint in MOTION_KEYWORDS if any(key in text for key in keys))


def _matched_hints(description: str, limit: int = 3) -> list[str]:
    text = description.lower()
    hints = [hint for keys, hint in MOTION_KEYWORDS if any(key in text for key in keys)]
    return hints[:limit]


def select_hero_scenes(episode: dict, scenes: list[str]) -> list[int]:
    """Return hero scene indices (1-based), best first.

    episode.json 'hero_scene' (int or list of ints) wins. Otherwise a keyword
    heuristic scores each scene; the unique highest score is the hero. If nothing
    scores, or the top score ties across scenes, default to scene 2 (clamped).
    """
    explicit = episode.get("hero_scene")
    if isinstance(explicit, bool):  # bool is an int subclass; reject it explicitly
        explicit = None
    if isinstance(explicit, int) and 1 <= explicit <= len(scenes):
        # Explicit hero leads; the rest still follow (budget caps decide how many
        # actually render — full-motion episodes animate every scene).
        rest = [i for i in range(1, len(scenes) + 1) if i != explicit]
        return [explicit, *rest]
    if isinstance(explicit, list):
        valid = [i for i in explicit if isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= len(scenes)]
        if valid:
            rest = [i for i in range(1, len(scenes) + 1) if i not in valid]
            return [*valid, *rest]

    scores = [(idx, _motion_score(desc)) for idx, desc in enumerate(scenes, start=1)]
    top = max((s for _idx, s in scores), default=0)
    leaders = [idx for idx, s in scores if s == top and s > 0]
    default_scene = 2 if len(scenes) >= 2 else 1
    hero = leaders[0] if len(leaders) == 1 else default_scene
    # Best first, then the remaining scenes by descending score (for max_clips > 1).
    rest = sorted((idx for idx, _s in scores if idx != hero), key=lambda i: (-dict(scores)[i], i))
    return [hero, *rest]


def _motion_hints(episode: dict, scene_index: int, scene_desc: str, config: dict) -> str:
    """Resolve ambient-motion hints for a scene: episode override, else keyword
    hints derived from the description, else the config default."""
    override = episode.get("hero_motion_hints")
    if isinstance(override, str) and override.strip():
        return override.strip()
    if isinstance(override, dict):  # per-scene mapping {"1": "..."} is tolerated
        per = override.get(str(scene_index))
        if isinstance(per, str) and per.strip():
            return per.strip()
    matched = _matched_hints(scene_desc)
    if matched:
        return ", ".join(matched)
    return str(config["animate"].get("default_motion_hints", "gentle ambient sway, soft light flicker"))


def _build_prompt(scene_desc: str, motion_hints: str, config: dict) -> str:
    suffix = config["animate"]["prompt_suffix"].format(motion=motion_hints)
    return f"{scene_desc.strip()} {suffix}"


# --------------------------------------------------------------------------- #
# Provider / fal job
# --------------------------------------------------------------------------- #
def _provider_conf(config: dict) -> tuple[str, str, float]:
    animate_cfg = config["animate"]
    provider = str(animate_cfg.get("provider", "grok")).lower()
    providers = animate_cfg.get("providers", {})
    if provider not in providers:
        raise ValueError(f"animate.provider '{provider}' not in animate.providers {list(providers)}")
    conf = providers[provider]
    return provider, str(conf["model"]), float(conf.get("usd_per_clip", 0.252))


def _submit_args(provider: str, prompt: str, image_url: str, config: dict) -> dict:
    animate_cfg = config["animate"]
    args = {
        "prompt": prompt,
        "image_url": image_url,
        "resolution": animate_cfg.get("resolution", "480p"),
        "aspect_ratio": animate_cfg.get("aspect_ratio", "9:16"),
    }
    if provider == "grok":
        args["duration"] = int(animate_cfg.get("duration_seconds", 5))
    else:  # wan turbo (fixed duration; skips the safety checker on pixel art)
        args["enable_safety_checker"] = False
    return args


def _flf_provider_chain(config: dict) -> list[tuple[str, dict]]:
    """Ordered (provider_key, provider_conf) list for first-last-frame mode, from
    config.animate.flf_providers. Skips keys with no provider entry."""
    animate_cfg = config["animate"]
    providers = animate_cfg.get("providers", {})
    chain: list[tuple[str, dict]] = []
    for key in animate_cfg.get("flf_providers", ["kling_o1", "wan_flf2v"]):
        conf = providers.get(str(key))
        if isinstance(conf, dict) and conf.get("model"):
            chain.append((str(key), conf))
    return chain


def _submit_args_flf(
    provider_key: str, prompt: str, start_url: str, end_url: str, conf: dict, config: dict
) -> dict:
    """Build the submit arguments for a first-last-frame job. Both Kling O1 and Wan
    FLF2V take start_image_url + end_image_url; only the extra knobs differ."""
    animate_cfg = config["animate"]
    args = {"prompt": prompt, "start_image_url": start_url, "end_image_url": end_url}
    if provider_key == "kling_o1":
        # Kling O1: duration is a STRING enum ("3".."10"); no aspect_ratio (the
        # output ratio follows the input keyframes, which are already 9:16).
        args["duration"] = str(int(conf.get("duration_seconds", animate_cfg.get("duration_seconds", 5))))
    else:  # wan_flf2v (and any future flf provider): resolution + skip safety checker
        args["resolution"] = animate_cfg.get("resolution", "480p")
        args["aspect_ratio"] = animate_cfg.get("aspect_ratio", "9:16")
        args["enable_safety_checker"] = False
    return args


def _extract_video_url(result: object) -> str | None:
    """Pull the mp4 URL out of a fal i2v result (shape varies by model)."""
    if not isinstance(result, dict):
        return None
    video = result.get("video") or result.get("videos")
    if isinstance(video, dict):
        return video.get("url")
    if isinstance(video, list) and video:
        first = video[0]
        return first.get("url") if isinstance(first, dict) else first
    return None


def _run_job(model: str, args: dict, poll_timeout: int) -> str:
    """Submit an i2v job, poll the queue until Completed or the deadline, and
    return the mp4 URL. Raises on timeout / API error / missing url."""
    import fal_client
    from fal_client import Completed

    handle = fal_client.submit(model, arguments=args)
    log("animate", f"submitted {model} req={handle.request_id}")
    deadline = time.time() + poll_timeout
    while True:
        status = handle.status()
        if isinstance(status, Completed):
            break
        if time.time() > deadline:
            raise TimeoutError(f"i2v job {handle.request_id} exceeded {poll_timeout}s")
        time.sleep(3)
    url = _extract_video_url(handle.get())
    if not url:
        raise RuntimeError(f"i2v job {handle.request_id} returned no video url")
    return url


def _download(url: str, dst: Path) -> None:
    """Stream the mp4 to disk with requests (certifi-backed TLS; the environment's
    urllib rejects the proxy cert chain)."""
    import requests

    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with dst.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if chunk:
                    handle.write(chunk)
    if dst.stat().st_size == 0:
        raise RuntimeError(f"downloaded empty file from {url}")


# --------------------------------------------------------------------------- #
# Frame extraction + SHARED-palette re-pixelate + boomerang encode
# --------------------------------------------------------------------------- #
def _even(value: int) -> int:
    """Round up to the nearest even number (yuv420p needs even dimensions)."""
    return value if value % 2 == 0 else value + 1


def _extract_frames(raw_mp4: Path, frames_dir: Path) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(raw_mp4), "-vsync", "0",
         str(frames_dir / "raw_%05d.png")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {result.stderr[-400:]}")
    frames = sorted(frames_dir.glob("raw_*.png"))
    if not frames:
        raise RuntimeError("ffmpeg produced no frames")
    return frames


def _grid_downscale(frame_rgb, downscale_width: int, prod_width: int):
    """Upscale a raw frame to the production width (so the grid chunk size matches
    the stills), then nearest-neighbour downscale to the pixel-grid width. Returns
    (small_rgb, prod_size)."""
    from PIL import Image

    width, height = frame_rgb.size
    prod_h = _even(round(height * (prod_width / width)))
    upscaled = frame_rgb.resize((prod_width, prod_h), Image.LANCZOS)
    small_w = max(1, min(downscale_width, prod_width))
    small_h = max(1, round(prod_h * (small_w / prod_width)))
    return upscaled.resize((small_w, small_h), Image.NEAREST), (prod_width, prod_h)


def _repixelate_shared(frames: list[Path], out_dir: Path, config: dict) -> list[Path]:
    """Re-pixelate every frame through the frame-0 palette (SHARED, no dither) so
    the grid is temporally stable. Returns the fixed frame paths in order."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    pix = config["pixelate"]
    prod_width = int(config["video"]["width"])
    downscale_width = int(pix["downscale_width"])
    palette_colors = int(pix["palette_colors"])
    shared = bool(config["animate"].get("shared_palette", True))

    palette_img = None
    prod_size: tuple[int, int] | None = None
    fixed: list[Path] = []
    for index, frame_path in enumerate(frames):
        with Image.open(frame_path) as image:
            frame_rgb = image.convert("RGB")
            if shared:
                small, size = _grid_downscale(frame_rgb, downscale_width, prod_width)
                if palette_img is None:  # derive the ONE palette from frame 0
                    palette_img = small.quantize(colors=max(2, palette_colors), method=Image.MEDIANCUT)
                    prod_size = size
                mapped = small.quantize(palette=palette_img, dither=Image.Dither.NONE).convert("RGB")
                out_image = mapped.resize(prod_size, Image.NEAREST)
            else:  # per-frame palette (matches the still pipeline; boils slightly)
                width, height = frame_rgb.size
                prod_h = _even(round(height * (prod_width / width)))
                upscaled = frame_rgb.resize((prod_width, prod_h), Image.LANCZOS)
                out_image = pixelate_image(upscaled, downscale_width, palette_colors)
        dst = out_dir / f"fix_{index:05d}.png"
        out_image.save(dst)
        fixed.append(dst)
    return fixed


def _encode_ordered(fixed: list[Path], order: list[int], out_mp4: Path, fps: int) -> None:
    """Encode the given frame ORDER into a seamless, audio-free clip. Atomic
    (tmp + rename), so no partial scene_N_video.mp4 ever appears."""
    with tempfile.TemporaryDirectory(prefix="anim_seq_") as seq_dir:
        seq = Path(seq_dir)
        for position, src_index in enumerate(order):
            dst = seq / f"b_{position:05d}.png"
            try:
                dst.hardlink_to(fixed[src_index])
            except OSError:
                shutil.copyfile(fixed[src_index], dst)
        tmp_mp4 = out_mp4.with_suffix(".tmp.mp4")
        result = subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(seq / "b_%05d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(MP4_CRF),
             "-an", str(tmp_mp4)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            tmp_mp4.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg encode failed: {result.stderr[-400:]}")
        tmp_mp4.replace(out_mp4)


def _bake_boomerang(fixed: list[Path], out_mp4: Path, fps: int) -> None:
    """Order frames forward then reverse (0..N-1,N-2..1) and encode a seamless,
    audio-free loop clip. A <Loop> restart lands on the turnaround -> no seam."""
    count = len(fixed)
    order = list(range(count)) + list(range(count - 2, 0, -1)) if count > 1 else [0]
    _encode_ordered(fixed, order, out_mp4, fps)


def _bake_forward(fixed: list[Path], out_mp4: Path, fps: int) -> None:
    """Encode frames in forward order ONLY (no reverse tail): a one-way action
    clip that Remotion plays once and then crossfades to its end still."""
    _encode_ordered(fixed, list(range(len(fixed))), out_mp4, fps)


def _render_clip(scene_png: Path, out_mp4: Path, scene_desc: str, motion_hints: str,
                 model: str, provider: str, config: dict) -> None:
    """One scene -> one scene_N_video.mp4. Raises on any failure (caller cleans up)."""
    import fal_client

    prompt = _build_prompt(scene_desc, motion_hints, config)
    log("animate", f"{out_mp4.name}: hints='{motion_hints}'")
    image_url = fal_client.upload_file(str(scene_png))
    video_url = _run_job(model, _submit_args(provider, prompt, image_url, config),
                         int(config["animate"].get("poll_timeout_seconds", 300)))

    with tempfile.TemporaryDirectory(prefix="animate_") as work_dir:
        work = Path(work_dir)
        raw_mp4 = work / "raw.mp4"
        _download(video_url, raw_mp4)
        frames = _extract_frames(raw_mp4, work / "raw_frames")
        fixed = _repixelate_shared(frames, work / "fixed_frames", config)
        log("animate", f"{out_mp4.name}: re-pixelated {len(fixed)} frames "
                       f"(shared_palette={config['animate'].get('shared_palette', True)})")
        _bake_boomerang(fixed, out_mp4, int(config["animate"].get("fps_out", 24)))


# --------------------------------------------------------------------------- #
# First-last-frame (flf) mode: two keyframes -> one-way action clip
# --------------------------------------------------------------------------- #
def _render_flf_clip(start_png: Path, end_png: Path, out_mp4: Path, prompt: str,
                     model: str, provider_key: str, conf: dict, config: dict) -> None:
    """Two stills (start + end) -> one FORWARD-ONLY scene_N_video.mp4. Raises on any
    failure (caller cleans up + tries the next provider)."""
    import fal_client

    log("animate", f"{out_mp4.name}: flf via {provider_key} ({model})")
    start_url = fal_client.upload_file(str(start_png))
    end_url = fal_client.upload_file(str(end_png))
    args = _submit_args_flf(provider_key, prompt, start_url, end_url, conf, config)
    video_url = _run_job(model, args, int(config["animate"].get("poll_timeout_seconds", 300)))

    with tempfile.TemporaryDirectory(prefix="animate_flf_") as work_dir:
        work = Path(work_dir)
        raw_mp4 = work / "raw.mp4"
        _download(video_url, raw_mp4)
        frames = _extract_frames(raw_mp4, work / "raw_frames")
        fixed = _repixelate_shared(frames, work / "fixed_frames", config)
        log("animate", f"{out_mp4.name}: re-pixelated {len(fixed)} frames "
                       f"(shared_palette={config['animate'].get('shared_palette', True)})")
        _bake_forward(fixed, out_mp4, int(config["animate"].get("fps_out", 24)))


def _animate_flf(paths: EpisodePaths, episode: dict, scenes: list[str],
                 config: dict, force: bool) -> dict[int, str]:
    """First-last-frame hero clip: animate the transition from scene_(hero-1) to
    scene_hero. Tries the flf provider chain (kling_o1 -> wan_flf2v) so a 404/error
    on the primary falls through to the cheaper fallback. Never blocks: on total
    failure the scene keeps its still."""
    animate_cfg = config["animate"]
    heroes = select_hero_scenes(episode, scenes)
    hero = heroes[0]
    if hero <= 1:
        log("animate", f"!!! flf needs a preceding scene, but hero={hero}; stills only")
        return {hero: "flf skipped (no start frame)"}

    out_mp4 = paths.scenes_dir / f"scene_{hero}_video.mp4"
    if out_mp4.exists() and not force:
        log("animate", f"scene_{hero}_video.mp4 exists, skipping (no cost)")
        return {hero: "cached"}

    start_png = paths.scenes_dir / f"scene_{hero - 1}.png"
    end_png = paths.scenes_dir / f"scene_{hero}.png"
    for name, png in (("start", start_png), ("end", end_png)):
        if not png.exists():
            log("animate", f"scene_{hero} flf {name} frame missing ({png.name}) -> stills only")
            return {hero: f"missing {name} still"}

    prompt = str(animate_cfg.get("flf_prompt", "")).strip()
    if not prompt:
        prompt = _build_prompt(scenes[hero - 1],
                               _motion_hints(episode, hero, scenes[hero - 1], config), config)

    max_usd = float(animate_cfg.get("max_usd_per_episode", 0.9))
    chain = _flf_provider_chain(config)
    if not chain:
        log("animate", "!!! no flf providers configured (animate.flf_providers) -> stills only")
        return {hero: "no flf provider"}

    for provider_key, conf in chain:
        usd = float(conf.get("usd_per_clip", 0.56))
        model = str(conf["model"])
        if usd > max_usd + 1e-9:
            log("animate", f"!!! COST GUARD: {provider_key} ${usd:.3f} > ${max_usd:.2f} budget -> skip")
            continue
        started = time.time()
        try:
            _render_flf_clip(start_png, end_png, out_mp4, prompt, model, provider_key, conf, config)
        except Exception as error:  # noqa: BLE001 - try the next provider, leave no partial
            out_mp4.unlink(missing_ok=True)
            out_mp4.with_suffix(".tmp.mp4").unlink(missing_ok=True)
            log("animate", "!!! ==================================================================")
            log("animate", f"!!! flf FAILED via {provider_key} for scene {hero}: {error}")
            log("animate", "!!! Trying the next flf provider (if any).")
            log("animate", "!!! ==================================================================")
            continue
        log("animate", f"scene_{hero}_video.mp4 ready in {time.time() - started:.1f}s "
                       f"via {provider_key} (~${usd:.3f})")
        return {hero: f"rendered ({provider_key}, ${usd:.3f})"}

    log("animate", f"!!! all flf providers failed for scene {hero}; falling back to still")
    return {hero: "error: all flf providers failed"}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def animate(episode_dir: Path, config: dict, force: bool = False) -> dict[int, str]:
    """Render hero-scene video clips. Returns {scene_index: status} for reporting.

    Never raises for an expected failure: a missing dependency, key, or a per-scene
    API/ffmpeg error is logged and the scene simply keeps its still.
    """
    animate_cfg = config.get("animate")
    if not animate_cfg or not animate_cfg.get("enable", True):
        log("animate", "disabled in config.animate -> stills only")
        return {}

    if not get_env("FAL_KEY"):
        log("animate", "!!! FAL_KEY not set (pipeline/.env) -> skipping i2v, stills only")
        return {}
    try:
        import fal_client  # noqa: F401
    except Exception as error:  # noqa: BLE001 - never block; fall back to stills
        log("animate", f"!!! fal_client unavailable ({error}); pip install fal-client -> stills only")
        return {}

    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    episode = read_json(paths.episode_json)
    scenes = list(episode.get("scenes", []))
    if not scenes:
        log("animate", "episode has no scenes -> nothing to animate")
        return {}

    # Mode: episode 'hero_mode' overrides config.animate.mode. 'flf' animates a
    # one-way action between two keyframes; 'boomerang' is the ambient i2v loop.
    # flf handles ONLY the hero scene, then falls through so the remaining scenes
    # still get their ambient loops (full-motion video, not a slideshow).
    mode = str(episode.get("hero_mode", animate_cfg.get("mode", "boomerang"))).strip().lower()
    flf_statuses: dict[int, str] = {}
    if mode == "flf":
        flf_statuses = _animate_flf(paths, episode, scenes, config, force)

    try:
        provider, model, usd_per_clip = _provider_conf(config)
    except Exception as error:  # noqa: BLE001
        log("animate", f"!!! bad provider config ({error}); stills only")
        return {}

    max_clips = int(animate_cfg.get("max_clips_per_episode", 1))
    max_usd = float(animate_cfg.get("max_usd_per_episode", 0.60))
    affordable = int(max_usd // usd_per_clip) if usd_per_clip > 0 else max_clips
    budget_clips = min(max_clips, affordable)

    heroes = select_hero_scenes(episode, scenes)
    log("animate", f"provider={provider} hero order={heroes} "
                   f"cap: {max_clips} clip(s) / ${max_usd:.2f} (${usd_per_clip:.3f}/clip) -> {budget_clips} allowed")

    if budget_clips <= 0:
        log("animate", f"!!! COST GUARD: ${max_usd:.2f} budget < ${usd_per_clip:.3f}/clip -> 0 clips, stills only")
        return {}

    statuses: dict[int, str] = dict(flf_statuses)
    spent = 0.0
    rendered = 0
    for scene_index in heroes:
        if scene_index in flf_statuses:
            continue  # the flf hero clip is handled above
        out_mp4 = paths.scenes_dir / f"scene_{scene_index}_video.mp4"
        if out_mp4.exists() and not force:
            statuses[scene_index] = "cached"
            log("animate", f"scene_{scene_index}_video.mp4 exists, skipping (no cost)")
            continue
        if rendered >= budget_clips:
            statuses[scene_index] = "skipped (budget)"
            continue

        scene_png = paths.scenes_dir / f"scene_{scene_index}.png"
        if not scene_png.exists():
            statuses[scene_index] = "missing still"
            log("animate", f"scene_{scene_index}.png missing -> cannot animate")
            continue

        motion_hints = _motion_hints(episode, scene_index, scenes[scene_index - 1], config)
        started = time.time()
        try:
            _render_clip(scene_png, out_mp4, scenes[scene_index - 1], motion_hints,
                         model, provider, config)
        except Exception as error:  # noqa: BLE001 - warn LOUDLY, leave no partial, keep going
            out_mp4.unlink(missing_ok=True)
            out_mp4.with_suffix(".tmp.mp4").unlink(missing_ok=True)
            statuses[scene_index] = f"error: {error}"
            log("animate", "!!! ==================================================================")
            log("animate", f"!!! i2v FAILED for scene {scene_index}: {error}")
            log("animate", "!!! Scene falls back to stills. Pipeline continues.")
            log("animate", "!!! ==================================================================")
            continue

        rendered += 1
        spent += usd_per_clip
        statuses[scene_index] = "rendered"
        log("animate", f"scene_{scene_index}_video.mp4 ready in {time.time() - started:.1f}s "
                       f"(~${usd_per_clip:.3f}, running total ${spent:.3f})")

    log("animate", f"{rendered} clip(s) rendered, ~${spent:.3f} spent "
                   f"({sum(1 for v in statuses.values() if v == 'cached')} cached)")
    return statuses


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Animate hero scene(s) into video clips via fal.ai i2v")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="re-render even if scene_N_video.mp4 exists")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    statuses = animate(Path(args.episode), load_config(), force=args.force)
    for index in sorted(statuses):
        print(f"scene_{index}: {statuses[index]}")


if __name__ == "__main__":
    main()
