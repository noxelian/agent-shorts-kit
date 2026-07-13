"""Shared fal.ai Grok Imagine image client (text-to-image + reference edit).

Used by scenes.py (scene continuity chaining) and mascot_poses.py (pose pack).
Mirrors the queue submit/poll/download pattern proven in animate.py:
  * fal_client.submit -> poll handle.status() until Completed (hard deadline);
  * download over requests (certifi-backed TLS; the environment's urllib
    rejects the proxy cert chain).

Model ids (fal.ai, verified against the live OpenAPI schema 2026-07-04):
  * text-to-image:  xai/grok-imagine-image        (~$0.02 / image)
  * reference edit: xai/grok-imagine-image/edit   (~$0.022 / image,
                    image_urls accepts UP TO 3 reference images)

Every function raises on failure; callers decide the fallback policy.
"""
from __future__ import annotations

import time
from pathlib import Path

from common import log

GROK_T2I_MODEL = "xai/grok-imagine-image"
GROK_EDIT_MODEL = "xai/grok-imagine-image/edit"
USD_PER_T2I = 0.02
USD_PER_EDIT = 0.022
MAX_EDIT_REFERENCES = 3


def upload_image(path: Path) -> str:
    """Upload a local image to fal storage and return its hosted URL."""
    import fal_client

    if not Path(path).exists():
        raise FileNotFoundError(f"cannot upload missing image: {path}")
    return fal_client.upload_file(str(path))


def _extract_image_url(result: object) -> str | None:
    """Pull the first image URL out of a Grok image result."""
    if not isinstance(result, dict):
        return None
    images = result.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            return first.get("url")
        if isinstance(first, str):
            return first
    return None


def _run_image_job(model: str, arguments: dict, poll_timeout: int) -> str:
    """Submit an image job, poll until Completed or deadline, return the URL."""
    import fal_client
    from fal_client import Completed

    handle = fal_client.submit(model, arguments=arguments)
    log("grok", f"submitted {model} req={handle.request_id}")
    deadline = time.time() + poll_timeout
    while True:
        status = handle.status()
        if isinstance(status, Completed):
            break
        if time.time() > deadline:
            raise TimeoutError(f"image job {handle.request_id} exceeded {poll_timeout}s")
        time.sleep(2)
    url = _extract_image_url(handle.get())
    if not url:
        raise RuntimeError(f"image job {handle.request_id} returned no image url")
    return url


def download(url: str, dst: Path) -> None:
    """Stream an image to disk with requests (certifi-backed TLS)."""
    import requests

    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with Path(dst).open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if chunk:
                    handle.write(chunk)
    if Path(dst).stat().st_size == 0:
        raise RuntimeError(f"downloaded empty file from {url}")


def text_to_image(
    prompt: str,
    dst: Path,
    *,
    model: str = GROK_T2I_MODEL,
    aspect_ratio: str = "9:16",
    resolution: str = "1k",
    poll_timeout: int = 240,
) -> str:
    """Generate one image from text, save it to dst, return its hosted URL."""
    url = _run_image_job(
        model,
        {
            "prompt": prompt,
            "num_images": 1,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": "png",
        },
        poll_timeout,
    )
    download(url, dst)
    return url


def edit_image(
    prompt: str,
    reference_urls: list[str],
    dst: Path,
    *,
    model: str = GROK_EDIT_MODEL,
    aspect_ratio: str = "auto",
    resolution: str = "1k",
    poll_timeout: int = 240,
) -> str:
    """Generate one image from up to 3 reference images + a prompt.

    Saves it to dst and returns its hosted URL. aspect_ratio 'auto' preserves
    the first reference image's ratio.
    """
    if not reference_urls:
        raise ValueError("edit_image needs at least one reference url")
    url = _run_image_job(
        model,
        {
            "prompt": prompt,
            "num_images": 1,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": "png",
            "image_urls": list(reference_urls[:MAX_EDIT_REFERENCES]),
        },
        poll_timeout,
    )
    download(url, dst)
    return url
