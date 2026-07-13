"""Shared mascot sprite helper: solid-background knockout to transparency.

Extracted from run.py's _prepare_mascot so both the render staging (run.py) and
the pose-pack stage (mascot_poses.py) knock out backgrounds identically:
flood-fill inward from each corner to a magenta marker, then turn every marker
pixel transparent.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from common import log

_MARKER = (255, 0, 255)
_FLOOD_THRESHOLD = 60


def knockout_background(src: Path, dst: Path) -> None:
    """Write dst as src with its solid background made transparent.

    Falls back to a plain copy if anything goes wrong (never raises), so a
    weird sprite degrades to an opaque image instead of blocking a render.
    """
    try:
        from PIL import Image, ImageDraw

        image = Image.open(src).convert("RGB")
        for corner in ((0, 0), (image.width - 1, 0), (0, image.height - 1),
                       (image.width - 1, image.height - 1)):
            ImageDraw.floodfill(image, corner, _MARKER, thresh=_FLOOD_THRESHOLD)
        rgba = image.convert("RGBA")
        pixels = rgba.load()
        for y in range(rgba.height):
            for x in range(rgba.width):
                r, g, b, _ = pixels[x, y]
                if (r, g, b) == _MARKER:
                    pixels[x, y] = (0, 0, 0, 0)
        rgba.save(dst)
    except Exception as error:  # noqa: BLE001 - never block the render on this
        log("mascot", f"background knockout skipped for {Path(src).name} ({error}); copying as-is")
        shutil.copyfile(src, dst)
