"""Shared pixelate utility: force a uniform pixel-grid look on any image.

Nearest-neighbor downscale to a small width, quantize to a limited palette,
then nearest-neighbor upscale back. Applied to EVERY scene image (whether it
came from codex or the placeholder generator) so the whole video shares one
consistent chunky pixel aesthetic.

Standalone:  python pixelate.py in.png out.png [--width 320] [--colors 32]
Importable:  from pixelate import pixelate_file, pixelate_image
"""
from __future__ import annotations

import argparse
from pathlib import Path


def pixelate_image(image, downscale_width: int, palette_colors: int):
    """Return a new pixelated PIL image. Pure: does not mutate the input."""
    from PIL import Image

    source = image.convert("RGB")
    width, height = source.size
    if width < 1 or height < 1:
        raise ValueError("cannot pixelate an empty image")

    small_w = max(1, min(downscale_width, width))
    small_h = max(1, round(height * (small_w / width)))

    small = source.resize((small_w, small_h), Image.NEAREST)
    quantized = small.quantize(colors=max(2, palette_colors), method=Image.MEDIANCUT).convert("RGB")
    return quantized.resize((width, height), Image.NEAREST)


def pixelate_file(src: Path, dst: Path, downscale_width: int = 320, palette_colors: int = 32) -> Path:
    from PIL import Image

    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"source image not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as image:
        result = pixelate_image(image, downscale_width, palette_colors)
    result.save(dst)
    return dst


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pixelate an image to a chunky retro grid")
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--width", type=int, default=320, help="downscale width in px")
    parser.add_argument("--colors", type=int, default=32, help="palette color count")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    out = pixelate_file(Path(args.src), Path(args.dst), args.width, args.colors)
    print(str(out))


if __name__ == "__main__":
    main()
