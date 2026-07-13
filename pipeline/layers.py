"""Stage 4.5: parallax layers. scene_N.png -> scene_N_fg.png + scene_N_bg.png.

Uses rembg (u2net, CPU) to cut the foreground subject out of each pixel scene,
then synthesises a crude background "plate" by diffusing surrounding pixels into
the hole the foreground leaves behind. Remotion drifts the two layers at
different speeds to fake depth.

This stage is OPTIONAL and must NEVER fail the pipeline:
  * scenes whose cutout is too small (<6%) or too large (>65%), or that raise any
    error, are simply skipped -> no layer files -> Remotion falls back to Ken Burns.

Standalone:  python layers.py --episode ../episodes/ep021-usa-beat-england-1950
Via run.py:  build_layers(episode_dir, config)
"""
from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path

from common import EpisodePaths, load_config, log, read_json

# Coverage guards: outside this band the cutout is untrustworthy (empty frame or
# nearly the whole image) so we skip the scene rather than ship a bad plate.
MIN_COVERAGE = 0.06
MAX_COVERAGE = 0.65


def _stub_pymatting() -> None:
    """rembg imports pymatting eagerly, but pymatting needs numba/llvmlite which
    has no prebuilt wheel for this Python/platform (and cannot compile here). We
    never use alpha matting, so register lightweight stubs for the three names
    rembg pulls in at import time. If the real package is present, do nothing."""
    if "pymatting" in sys.modules:
        return
    try:
        import pymatting  # noqa: F401
        return
    except Exception:  # noqa: BLE001 - fall through to the stub
        pass

    def _unavailable(*_args, **_kwargs):  # pragma: no cover - never reached
        raise RuntimeError("pymatting alpha matting is unavailable in this environment")

    def _module(name: str) -> types.ModuleType:
        module = types.ModuleType(name)
        sys.modules[name] = module
        return module

    root = _module("pymatting")
    root.alpha = _module("pymatting.alpha")
    root.foreground = _module("pymatting.foreground")
    root.util = _module("pymatting.util")
    for path, attr in (
        ("pymatting.alpha.estimate_alpha_cf", "estimate_alpha_cf"),
        ("pymatting.foreground.estimate_foreground_ml", "estimate_foreground_ml"),
        ("pymatting.util.util", "stack_images"),
    ):
        setattr(_module(path), attr, _unavailable)


def _mask_coverage(alpha) -> float:
    """Fraction of pixels the foreground mask actually covers (alpha > 0.5)."""
    import numpy as np

    values = np.asarray(alpha, dtype="float32") / 255.0
    return float((values > 0.5).mean())


def _build_plate(original, alpha, dilate_px: int = 10):
    """Fill the foreground hole with structure-aware OpenCV inpainting.

    The old blur-diffusion plate left a smeared ghost of the cutout subject in
    the hole, which became a visible double image once the fg layer drifted more
    than a few px (ep023 QA). TELEA extends the surrounding background structure
    into the hole instead; the filled region is then re-quantized to the scene's
    own 128-colour palette so the exposed sliver reads as pixel art, not
    airbrush. Falls back to blur diffusion if OpenCV is unavailable.
    """
    import numpy as np
    from PIL import Image, ImageFilter

    rgb = np.asarray(original.convert("RGB"), dtype="uint8")
    mask_img = Image.fromarray((np.asarray(alpha) > 128).astype("uint8") * 255)
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(dilate_px))
    mask = ((np.asarray(mask_img, dtype="float32") / 255.0 > 0.12).astype("uint8")) * 255

    try:
        import cv2

        filled = cv2.inpaint(rgb, mask, inpaintRadius=12, flags=cv2.INPAINT_TELEA)
        palette_ref = original.convert("RGB").quantize(colors=128, method=Image.MEDIANCUT)
        quant = np.asarray(
            Image.fromarray(filled).quantize(palette=palette_ref, dither=Image.NONE).convert("RGB")
        )
        result = rgb.copy()
        hole = mask > 0
        result[hole] = quant[hole]
        return Image.fromarray(result)
    except Exception as error:  # noqa: BLE001 - plate must never fail the pipeline
        log("layers", f"cv2 inpaint unavailable/failed ({error}) -> blur-diffusion fallback")
        return _build_plate_blur(original, alpha, dilate_px)


def _build_plate_blur(original, alpha, dilate_px: int = 10, iters: int = 16, radius: int = 14):
    """Legacy fallback: diffuse neighbouring pixels into the hole by repeated
    blurring. Leaves a soft ghost of the subject - only used without OpenCV."""
    import numpy as np
    from PIL import Image, ImageFilter

    rgb = np.asarray(original.convert("RGB"), dtype="float32")

    # Dilate the mask a touch (blur + threshold) so the fg silhouette edge, not
    # just its interior, is covered by the plate.
    mask_img = Image.fromarray((np.asarray(alpha) > 128).astype("uint8") * 255)
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(dilate_px))
    mask = np.asarray(mask_img, dtype="float32") / 255.0 > 0.12

    filled = rgb.copy()
    # Seed the hole with the global mean so early passes have something to blur.
    if mask.any():
        known = ~mask
        if known.any():
            filled[mask] = rgb[known].mean(axis=0)

    for _ in range(iters):
        current = Image.fromarray(np.clip(filled, 0, 255).astype("uint8"))
        blurred = np.asarray(
            current.filter(ImageFilter.GaussianBlur(radius)), dtype="float32"
        )
        filled[mask] = blurred[mask]

    return Image.fromarray(np.clip(filled, 0, 255).astype("uint8"))


def _cut_scene(src: Path, fg_dst: Path, bg_dst: Path) -> tuple[str, float]:
    """Produce fg + bg for one scene. Returns (status, coverage)."""
    from PIL import Image

    _stub_pymatting()
    from rembg import remove

    original = Image.open(src).convert("RGB")
    cutout = remove(original).convert("RGBA")
    alpha = cutout.split()[3]

    # rembg on pixel art returns SOFT alpha for weakly-detected subjects, which
    # rendered as semi-transparent "ghost" characters floating over the plate
    # (ep023 QA). Binarize: a pixel is either fully foreground or fully
    # background. fg colours come from the untouched original because rembg's
    # edge decontamination also washes out pixel-art colours.
    hard_alpha = alpha.point(lambda value: 255 if value > 128 else 0)
    # rembg also leaves alpha pinholes INSIDE subjects (plate speckles showing
    # through characters). Close them: any transparent pocket fully enclosed by
    # foreground becomes foreground.
    import numpy as np
    from scipy.ndimage import binary_fill_holes

    hard_alpha = Image.fromarray(
        (binary_fill_holes(np.asarray(hard_alpha) > 0) * 255).astype("uint8")
    )

    coverage = _mask_coverage(hard_alpha)
    if coverage < MIN_COVERAGE:
        return f"skip (fg {coverage:.1%} < {MIN_COVERAGE:.0%})", coverage
    if coverage > MAX_COVERAGE:
        return f"skip (fg {coverage:.1%} > {MAX_COVERAGE:.0%})", coverage

    fg = original.convert("RGBA")
    fg.putalpha(hard_alpha)
    plate = _build_plate(original, hard_alpha)
    fg.save(fg_dst)
    plate.save(bg_dst)
    return "layered", coverage


def build_layers(episode_dir: Path, config: dict, force: bool = False) -> dict[int, str]:
    """For every scene, try to build fg/bg layers. Skips gracefully on failure.

    Returns {scene_index (1-based): status string} for reporting.
    """
    motion = config.get("motion", {})
    if not motion.get("parallax", {}).get("enable", True):
        log("layers", "parallax disabled in config.motion -> skipping stage")
        return {}

    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    episode = read_json(paths.episode_json) if paths.episode_json.exists() else {}
    explicit_scene_count = episode.get("scene_count")
    scenes = episode.get("scenes")
    if isinstance(explicit_scene_count, int) and not isinstance(explicit_scene_count, bool) and explicit_scene_count > 0:
        scene_count = explicit_scene_count
    elif isinstance(scenes, list) and scenes:
        scene_count = len(scenes)
    else:
        scene_count = int(config["video"]["scene_count"])
    statuses: dict[int, str] = {}

    for index in range(1, scene_count + 1):
        src = paths.scenes_dir / f"scene_{index}.png"
        fg_dst = paths.scenes_dir / f"scene_{index}_fg.png"
        bg_dst = paths.scenes_dir / f"scene_{index}_bg.png"
        # Sentinel recording a scene that was deliberately skipped (bad coverage /
        # error) so later runs do not re-invoke rembg on it every render.
        skip_marker = paths.scenes_dir / f"scene_{index}.nolayer"

        if force:
            skip_marker.unlink(missing_ok=True)

        if not src.exists():
            statuses[index] = "missing scene png"
            log("layers", f"scene_{index}: source png missing -> fallback")
            continue

        if fg_dst.exists() and bg_dst.exists() and not force:
            statuses[index] = "cached"
            log("layers", f"scene_{index}: layers exist, skipping")
            continue

        if skip_marker.exists() and not force:
            statuses[index] = "cached skip"
            log("layers", f"scene_{index}: previously skipped, not retrying")
            continue

        try:
            status, coverage = _cut_scene(src, fg_dst, bg_dst)
        except Exception as error:  # noqa: BLE001 - never fail the pipeline here
            statuses[index] = f"error: {error}"
            log("layers", f"scene_{index}: rembg error ({error}) -> fallback")
            # Remove any half-written outputs so Remotion sees a clean fallback.
            fg_dst.unlink(missing_ok=True)
            bg_dst.unlink(missing_ok=True)
            continue

        statuses[index] = status
        if status != "layered":
            # Below/above the coverage band: leave no files so Remotion falls back,
            # and drop a sentinel so we do not re-run rembg here next time.
            fg_dst.unlink(missing_ok=True)
            bg_dst.unlink(missing_ok=True)
            skip_marker.write_text(status, encoding="utf-8")
        else:
            skip_marker.unlink(missing_ok=True)
        log("layers", f"scene_{index}: {status}")

    layered = sum(1 for value in statuses.values() if value in ("layered", "cached"))
    log("layers", f"{layered}/{scene_count} scenes layered")
    return statuses


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build parallax fg/bg layers for scenes")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="rebuild even if layers exist")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    statuses = build_layers(Path(args.episode), load_config(), force=args.force)
    for index in sorted(statuses):
        print(f"scene_{index}: {statuses[index]}")


if __name__ == "__main__":
    main()
