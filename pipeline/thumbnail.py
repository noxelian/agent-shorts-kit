"""Stage 6 (optional): episode -> out/thumb_vertical.png + out/thumb_wide.png.

YouTube Shorts mostly ignores custom thumbnails in the feed, but they DO show
on the channel grid, and the weekly long-form compilations need real
clickable thumbnails -- so we build both a 1080x1920 (vertical/Shorts-grid)
and a 1280x720 (widescreen/compilation) thumbnail from the same hero scene.

Composition (both formats):
  1. hero scene image, cover-cropped to the target aspect ratio
  2. dark gradient (bottom for vertical, left for wide) for text contrast
  3. huge bold outlined title (3-5 punchiest words from episode.json title),
     with one accent-colored word, wrapped to 2-3 lines -- crisp, never pixelated
  4. optional knocked-out mascot in a corner with a subtle hard drop shadow

Only the scene layer is re-pixelated after cropping (cropping/scaling from the
portrait source can soften the pixel grid); text and mascot stay crisp.

Standalone:  python thumbnail.py --episode ../episodes/ep021-usa-beat-england-1950
Via run.py:  build_thumbnails(episode_dir, config)
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import EpisodePaths, PROJECT_DIR, get_env, load_config, log, read_json
from pixelate import pixelate_image

_EMOJI_STRIP_RE = re.compile(r"[^\w\s'\-]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# Title extraction: episode.json title -> 3-5 punchy uppercase words + accent
# --------------------------------------------------------------------------

def _clean_words(segment: str) -> list[str]:
    """Strip emoji/punctuation (keep letters, digits, apostrophes, hyphens)."""
    cleaned = _EMOJI_STRIP_RE.sub(" ", segment)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned.split(" ") if cleaned else []


def pick_title_words(title: str, title_cfg: dict) -> list[str]:
    """3-5 punchiest words derived from the episode title.

    Takes the text before the first em-dash (if that segment still has a
    real subject, i.e. >= min_words tokens), else the full title. Drops
    grammatical stopwords, then keeps the LAST max_words tokens (the tail of
    a hook sentence usually carries the punchline / subject).
    """
    min_words = int(title_cfg.get("min_words", 3))
    max_words = int(title_cfg.get("max_words", 5))
    stopwords = {w.lower() for w in title_cfg.get("stopwords", [])}

    segment = title
    if "—" in title:  # em-dash
        before = title.split("—", 1)[0].strip()
        if len(before.split()) >= min_words:
            segment = before

    tokens = _clean_words(segment)
    if not tokens:
        tokens = _clean_words(title) or ["HISTORY"]

    filtered = [t for t in tokens if t.lower() not in stopwords]
    base = filtered if len(filtered) >= min_words else tokens

    if len(base) > max_words:
        base = base[-max_words:]
    elif len(base) < min_words and len(tokens) >= min_words:
        base = tokens[-min_words:]

    return [w.upper() for w in base]


def pick_accent_index(words: list[str]) -> int:
    """Index of the single most emotional word: a number if present, else last."""
    for index, word in enumerate(words):
        if any(char.isdigit() for char in word):
            return index
    return len(words) - 1


# --------------------------------------------------------------------------
# Font / text layout helpers
# --------------------------------------------------------------------------

def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # noqa: E203


def _load_title_font(font_paths: list[str], size: int):
    from PIL import ImageFont

    for candidate in font_paths:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:  # noqa: BLE001 - try the next candidate
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Older Pillow: load_default() has no size arg (fixed small bitmap font).
        return ImageFont.load_default()


def _greedy_wrap(draw, words: list[str], font, max_width: float) -> list[list[str]]:
    lines: list[list[str]] = []
    current: list[str] = []
    for word in words:
        trial = current + [word]
        width = draw.textlength(" ".join(trial), font=font)
        if width <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = [word]
    if current:
        lines.append(current)
    return lines


def _fit_title(
    draw, words: list[str], font_paths: list[str], max_width: int, max_height: int,
    size_max: int, size_min: int, max_lines: int, line_spacing_ratio: float,
    step: int = 4,
) -> tuple[object, list[list[str]], int]:
    """Search downward from size_max for the largest font that wraps the title
    into at most max_lines lines within (max_width, max_height)."""
    size = size_max
    smallest_fallback: tuple[object, list[list[str]], int] | None = None
    while size >= size_min:
        font = _load_title_font(font_paths, size)
        lines = _greedy_wrap(draw, words, font, max_width)
        line_height = int(size * line_spacing_ratio)
        block_height = line_height * len(lines)
        if len(lines) <= max_lines and block_height <= max_height:
            return font, lines, line_height
        smallest_fallback = (font, lines, line_height)
        size -= step

    # No size in [size_min, size_max] wrapped the title into <= max_lines lines
    # (e.g. several long words that never pair up within max_width even at the
    # smallest legible size). Accept the size_min wrap AS-IS rather than force-
    # merging lines: every individual line still came out of _greedy_wrap, so
    # each one already fits max_width -- it may just run to more than max_lines
    # lines, which is a fine look for a stacked headline. NEVER return a merged
    # line that skips the max_width check, or text will overflow the canvas.
    assert smallest_fallback is not None
    return smallest_fallback


def _draw_title_lines(
    draw, lines: list[list[str]], accent_flat_index: int, font, line_height: int,
    center_x: int, top_y: int, text_color: tuple, accent_color: tuple,
    outline_color: tuple, outline_px: int, align: str = "center",
    left_x: int | None = None,
) -> None:
    """Render wrapped title lines word-by-word so exactly one word can be
    recolored, each word/space measured individually so centering is exact."""
    flat_index = 0
    y = top_y
    for line in lines:
        widths = [draw.textlength(word, font=font) for word in line]
        space_w = draw.textlength(" ", font=font)
        line_width = sum(widths) + space_w * (len(line) - 1 if line else 0)
        if align == "left" and left_x is not None:
            x = left_x
        else:
            x = center_x - line_width / 2
        for word, word_w in zip(line, widths):
            fill = accent_color if flat_index == accent_flat_index else text_color
            draw.text(
                (x, y), word, font=font, fill=fill,
                stroke_width=outline_px, stroke_fill=outline_color,
            )
            x += word_w + space_w
            flat_index += 1
        y += line_height


# --------------------------------------------------------------------------
# Scene cropping + gradient
# --------------------------------------------------------------------------

def _cover_crop(image, target_w: int, target_h: int, focus_y: float = 0.5):
    from PIL import Image

    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    if abs(scale - 1.0) < 1e-6:
        resized = image
    else:
        new_size = (round(src_w * scale), round(src_h * scale))
        resized = image.resize(new_size, Image.LANCZOS)

    new_w, new_h = resized.size
    x = round((new_w - target_w) / 2)
    max_y_offset = max(0, new_h - target_h)
    y = round(max_y_offset * focus_y)
    x = max(0, min(x, max(0, new_w - target_w)))
    y = max(0, min(y, max_y_offset))
    return resized.crop((x, y, x + target_w, y + target_h))


def _vertical_gradient_alpha(width: int, height: int, start_frac: float, max_opacity: float):
    import numpy as np
    from PIL import Image

    rows = np.arange(height, dtype="float32")
    start_y = height * (1 - start_frac)
    span = max(1.0, height - start_y)
    alpha = np.clip((rows - start_y) / span, 0.0, 1.0) * (max_opacity * 255)
    alpha_2d = np.repeat(alpha.astype("uint8").reshape(height, 1), width, axis=1)
    return Image.fromarray(alpha_2d, mode="L")


def _left_gradient_alpha(width: int, height: int, end_frac: float, max_opacity: float):
    import numpy as np
    from PIL import Image

    cols = np.arange(width, dtype="float32")
    end_x = max(1.0, width * end_frac)
    alpha = np.clip(1.0 - cols / end_x, 0.0, 1.0) * (max_opacity * 255)
    alpha_2d = np.repeat(alpha.astype("uint8").reshape(1, width), height, axis=0)
    return Image.fromarray(alpha_2d, mode="L")


def _apply_gradient(base_rgba, alpha_mask) -> None:
    """Alpha-composite a pure-black overlay masked by alpha_mask onto base_rgba
    IN PLACE. base_rgba is always our own scratch canvas built earlier in the
    same call, never the caller's source image, so mutating it here is safe."""
    from PIL import Image

    overlay = Image.new("RGBA", base_rgba.size, (0, 0, 0, 255))
    overlay.putalpha(alpha_mask)
    base_rgba.alpha_composite(overlay)


# --------------------------------------------------------------------------
# Mascot: background knockout (cribbed from run.py) + drop shadow
# --------------------------------------------------------------------------

def _knockout_mascot(src: Path):
    """Flood-fill the mascot's solid background to transparency from each
    corner, same technique as run.py's _prepare_mascot for the video render."""
    from PIL import Image, ImageDraw

    image = Image.open(src).convert("RGB")
    marker = (255, 0, 255)
    for corner in (
        (0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1),
    ):
        ImageDraw.floodfill(image, corner, marker, thresh=60)
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, _a = pixels[x, y]
            if (r, g, b) == marker:
                pixels[x, y] = (0, 0, 0, 0)
    return rgba


def _paste_mascot_with_shadow(
    canvas, mascot_rgba, anchor_xy: tuple[int, int], size_px: int, mascot_cfg: dict,
) -> None:
    from PIL import Image, ImageFilter

    resized = mascot_rgba.resize((size_px, size_px), Image.NEAREST)
    alpha = resized.split()[3]

    offset = int(mascot_cfg.get("shadow_offset_px", 14))
    blur = int(mascot_cfg.get("shadow_blur_radius", 6))
    opacity = int(mascot_cfg.get("shadow_opacity", 150))

    shadow_alpha = alpha.point(lambda a: min(a, opacity))
    if blur > 0:
        shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(blur))
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_rgba = Image.new("RGBA", resized.size, (0, 0, 0, 0))
    shadow_rgba.putalpha(shadow_alpha)
    shadow_layer.paste(shadow_rgba, (anchor_xy[0] + offset, anchor_xy[1] + offset), shadow_rgba)
    canvas.alpha_composite(shadow_layer)
    canvas.alpha_composite(resized, anchor_xy)


# --------------------------------------------------------------------------
# Per-format composition
# --------------------------------------------------------------------------

_TEXT_MASCOT_GAP_PX = 36  # gap between the title block and the mascot corner (vertical only)


def _build_background(scene_image, fmt: str, width: int, height: int, config: dict):
    """Cover-crop the hero scene to (width, height), pixelate it, and paint the
    dark contrast gradient on top. Returns an RGBA canvas."""
    thumb_cfg = config["thumbnail"]
    pix_cfg = config["pixelate"]
    gradient_cfg = thumb_cfg["gradient"]

    focus_y = 0.5 if fmt == "vertical" else float(thumb_cfg.get("wide_crop_focus_y", 0.5))
    cropped = _cover_crop(scene_image, width, height, focus_y=focus_y)
    pixelated = pixelate_image(cropped, pix_cfg["downscale_width"], pix_cfg["palette_colors"])
    canvas = pixelated.convert("RGBA")

    if fmt == "vertical":
        alpha_mask = _vertical_gradient_alpha(
            width, height, gradient_cfg["vertical_bottom_start_frac"], gradient_cfg["max_opacity"],
        )
    else:
        alpha_mask = _left_gradient_alpha(
            width, height, gradient_cfg["wide_left_end_frac"], gradient_cfg["max_opacity"],
        )
    _apply_gradient(canvas, alpha_mask)
    return canvas


def _mascot_anchor(fmt: str, width: int, height: int, mascot_cfg: dict) -> tuple[int, int, int]:
    """Corner position + size for the mascot: bottom-left (vertical) or
    bottom-right (wide)."""
    margin = int(mascot_cfg["margin_px"])
    size = int(mascot_cfg["vertical_size_px" if fmt == "vertical" else "wide_size_px"])
    x = margin if fmt == "vertical" else width - size - margin
    y = height - size - margin
    return x, y, size


def _draw_title_overlay(
    draw, title_words: list[str], accent_index: int, fmt: str,
    width: int, height: int, mascot_xy: tuple[int, int], title_cfg: dict,
) -> None:
    """Fit + render the title text, positioned so it never overlaps the mascot
    corner: stacked above it (vertical) or to its left (wide)."""
    text_margin = int(title_cfg["margin_px"])
    text_color = _hex_to_rgb(title_cfg["text_color"])
    accent_color = _hex_to_rgb(title_cfg["accent_color"])
    outline_color = _hex_to_rgb(title_cfg["outline_color"])

    if fmt == "vertical":
        max_text_width = width - 2 * text_margin
        text_bottom = mascot_xy[1] - _TEXT_MASCOT_GAP_PX
        max_text_height = text_bottom - text_margin
        size_max, size_min = title_cfg["vertical_font_size_max"], title_cfg["vertical_font_size_min"]
    else:
        max_text_width = mascot_xy[0] - 2 * text_margin
        text_bottom = height - text_margin
        max_text_height = height - 2 * text_margin
        size_max, size_min = title_cfg["wide_font_size_max"], title_cfg["wide_font_size_min"]

    font, lines, line_height = _fit_title(
        draw, title_words, title_cfg["fonts"], max_text_width, max_text_height,
        size_max, size_min, title_cfg["max_lines"], title_cfg["line_spacing_ratio"],
    )
    block_height = line_height * len(lines)
    outline_px = max(2, round(font.size * title_cfg["outline_px_ratio"])) if hasattr(font, "size") else 4

    if fmt == "vertical":
        _draw_title_lines(
            draw, lines, accent_index, font, line_height,
            center_x=width // 2, top_y=text_bottom - block_height, text_color=text_color,
            accent_color=accent_color, outline_color=outline_color, outline_px=outline_px,
            align="center",
        )
    else:
        top_y = max(text_margin, (height - block_height) // 2)
        _draw_title_lines(
            draw, lines, accent_index, font, line_height,
            center_x=0, top_y=top_y, text_color=text_color,
            accent_color=accent_color, outline_color=outline_color, outline_px=outline_px,
            align="left", left_x=text_margin,
        )


def _compose_thumbnail(
    scene_image, mascot_rgba, title_words: list[str], accent_index: int,
    fmt: str, config: dict, dst: Path,
) -> None:
    from PIL import ImageDraw

    thumb_cfg = config["thumbnail"]
    mascot_cfg = thumb_cfg["mascot"]
    width, height = (
        (thumb_cfg["vertical"]["width"], thumb_cfg["vertical"]["height"])
        if fmt == "vertical"
        else (thumb_cfg["wide"]["width"], thumb_cfg["wide"]["height"])
    )

    canvas = _build_background(scene_image, fmt, width, height, config)

    mascot_x, mascot_y, mascot_size = _mascot_anchor(fmt, width, height, mascot_cfg)
    _paste_mascot_with_shadow(canvas, mascot_rgba, (mascot_x, mascot_y), mascot_size, mascot_cfg)

    draw = ImageDraw.Draw(canvas)
    _draw_title_overlay(
        draw, title_words, accent_index, fmt, width, height,
        (mascot_x, mascot_y), thumb_cfg["title"],
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dst)


# --------------------------------------------------------------------------
# Portrait mode (default): one Grok-edit reaction shot + ONE big burned word
# --------------------------------------------------------------------------

def pick_thumbnail_word(episode: dict, title_cfg: dict) -> str:
    """The single burn word. episode.json 'thumbnail_word' wins; else the punchiest
    short word from the title (a number/scoreline if present, else the shortest
    non-stopword) with a '!' appended when it carries no punctuation of its own."""
    explicit = episode.get("thumbnail_word")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().upper()

    title = episode.get("title") or episode.get("topic") or "HISTORY"
    words = pick_title_words(title, title_cfg)  # already uppercased, stopwords dropped
    if not words:
        return "HISTORY!"
    with_digit = [w for w in words if any(c.isdigit() for c in w)]
    chosen = with_digit[0] if with_digit else min(words, key=len)
    if not any(c in chosen for c in "!?.-–—0123456789"):
        chosen = f"{chosen}!"
    return chosen


def _mascot_reference() -> Path:
    for name in ("mascot.png", "character.png", "raccoon-test.png", "raccoon.png"):
        candidate = PROJECT_DIR / "assets" / "mascot" / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError("no mascot PNG found (expected mascot.png or character.png)")


def _portrait_prompt(episode: dict, portrait_cfg: dict) -> str:
    emotion = episode.get("thumbnail_emotion") or portrait_cfg["default_emotion"]
    backdrop = episode.get("thumbnail_backdrop") or portrait_cfg["default_backdrop"]
    return portrait_cfg["edit_prompt_template"].format(emotion=emotion, backdrop=backdrop)


def _generate_portrait_base(episode: dict, config: dict, base_path: Path, force: bool):
    """Grok-edit ONE reaction portrait from the mascot reference, cached at
    base_path (resumable, no re-cost). Returns a PIL RGB image. Raises on any
    failure so the caller can fall back to title mode."""
    from PIL import Image

    portrait_cfg = config["thumbnail"]["portrait"]
    if base_path.exists() and not force:
        log("thumbnail", f"portrait base cached, reusing ({base_path.name}, no cost)")
        return Image.open(base_path).convert("RGB")

    if not get_env("FAL_KEY"):
        raise RuntimeError("FAL_KEY not set -> cannot generate portrait thumbnail")

    adapter = config.get("scenes_adapter", {})
    budget = float(adapter.get("max_usd_per_episode", 0.30))
    cost = float(portrait_cfg.get("usd_per_image", 0.022))
    if cost > budget + 1e-9:
        raise RuntimeError(f"portrait cost ${cost:.3f} exceeds budget ${budget:.2f}")

    import grok_image

    reference = _mascot_reference()
    prompt = _portrait_prompt(episode, portrait_cfg)
    log("thumbnail", f"generating portrait via grok edit (ref={reference.name}, ~${cost:.3f})")
    reference_url = grok_image.upload_image(reference)
    grok_image.edit_image(
        prompt, [reference_url], base_path,
        model=str(adapter.get("grok_edit_model", grok_image.GROK_EDIT_MODEL)),
        aspect_ratio="9:16", resolution=str(adapter.get("grok_resolution", "1k")),
        poll_timeout=int(adapter.get("grok_poll_timeout_seconds", 240)),
    )
    log("thumbnail", f"portrait base ready -> {base_path}")
    return Image.open(base_path).convert("RGB")


def _fit_single_word(draw, word: str, font_paths: list[str], max_width: int,
                     size_max: int, size_min: int, outline_ratio: float, step: int = 6):
    """Largest font (size_max..size_min) whose stroked word fits max_width."""
    size = size_max
    fallback = None
    while size >= size_min:
        font = _load_title_font(font_paths, size)
        outline_px = max(2, round(size * outline_ratio))
        bbox = draw.textbbox((0, 0), word, font=font, stroke_width=outline_px)
        if (bbox[2] - bbox[0]) <= max_width:
            return font, outline_px
        fallback = (font, outline_px)
        size -= step
    assert fallback is not None
    return fallback


def _compose_portrait(base_image, word: str, fmt: str, config: dict, dst: Path) -> None:
    from PIL import Image, ImageDraw

    thumb_cfg = config["thumbnail"]
    portrait_cfg = thumb_cfg["portrait"]
    pix_cfg = config["pixelate"]
    width, height = (
        (thumb_cfg["vertical"]["width"], thumb_cfg["vertical"]["height"])
        if fmt == "vertical"
        else (thumb_cfg["wide"]["width"], thumb_cfg["wide"]["height"])
    )

    if fmt == "wide":
        # A portrait base cover-cropped to 16:9 decapitates the face. Compose
        # instead: full face fit-by-height on the left, word centered in the
        # remaining right area, over a blurred+darkened crop of the same base.
        from PIL import ImageEnhance, ImageFilter

        bg = _cover_crop(base_image, width, height, focus_y=0.3)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=14))
        bg = ImageEnhance.Brightness(bg).enhance(0.5)
        bg = pixelate_image(bg, pix_cfg["downscale_width"], pix_cfg["palette_colors"])
        canvas = bg.convert("RGBA")

        face_w = round(base_image.width * (height / base_image.height))
        face = base_image.resize((face_w, height), resample=Image.LANCZOS)
        face_x = int(width * 0.03)
        canvas.paste(face.convert("RGBA"), (face_x, 0))

        draw = ImageDraw.Draw(canvas)
        region_x = face_x + face_w
        region_w = width - region_x
        margin = int(thumb_cfg["title"]["margin_px"])
        font, outline_px = _fit_single_word(
            draw, word, thumb_cfg["title"]["fonts"], region_w - 2 * margin,
            int(portrait_cfg["word_font_size_max"]), int(portrait_cfg["word_font_size_min"]),
            float(portrait_cfg["word_outline_px_ratio"]),
        )
        accent = any(c.isdigit() for c in word)
        fill = _hex_to_rgb(
            portrait_cfg["word_accent_color"] if accent else portrait_cfg["word_color"])
        outline_color = _hex_to_rgb(portrait_cfg["word_outline_color"])
        bbox = draw.textbbox((0, 0), word, font=font, stroke_width=outline_px)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = region_x + (region_w - text_w) / 2 - bbox[0]
        y = (height - text_h) / 2 - bbox[1]
        draw.text((x, y), word, font=font, fill=fill,
                  stroke_width=outline_px, stroke_fill=outline_color)

        dst.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(dst)
        return

    cropped = _cover_crop(base_image, width, height,
                          focus_y=float(portrait_cfg.get("focus_y", 0.3)))
    pixelated = pixelate_image(cropped, pix_cfg["downscale_width"], pix_cfg["palette_colors"])
    canvas = pixelated.convert("RGBA")

    # Faint bottom gradient so the word reads over a busy backdrop (the hard
    # outline does the heavy lifting; this is a gentle assist).
    alpha_mask = _vertical_gradient_alpha(width, height, 0.42, 0.55)
    _apply_gradient(canvas, alpha_mask)

    draw = ImageDraw.Draw(canvas)
    margin = int(thumb_cfg["title"]["margin_px"])
    font, outline_px = _fit_single_word(
        draw, word, thumb_cfg["title"]["fonts"], width - 2 * margin,
        int(portrait_cfg["word_font_size_max"]), int(portrait_cfg["word_font_size_min"]),
        float(portrait_cfg["word_outline_px_ratio"]),
    )
    accent = any(c.isdigit() for c in word)
    fill = _hex_to_rgb(portrait_cfg["word_accent_color"] if accent else portrait_cfg["word_color"])
    outline_color = _hex_to_rgb(portrait_cfg["word_outline_color"])

    bbox = draw.textbbox((0, 0), word, font=font, stroke_width=outline_px)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - text_w) / 2 - bbox[0]
    bottom_gap = int(height * float(portrait_cfg.get("word_bottom_frac", 0.24)))
    y = height - bottom_gap - text_h - bbox[1]
    draw.text((x, y), word, font=font, fill=fill,
              stroke_width=outline_px, stroke_fill=outline_color)

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dst)


def _build_portrait(episode: dict, config: dict, paths: EpisodePaths,
                    thumb_vertical: Path, thumb_wide: Path, force: bool) -> dict:
    base_path = paths.out_dir / "thumb_portrait_base.png"
    base_image = _generate_portrait_base(episode, config, base_path, force)
    word = pick_thumbnail_word(episode, config["thumbnail"]["title"])
    log("thumbnail", f"portrait burn word: '{word}'")

    _compose_portrait(base_image, word, "vertical", config, thumb_vertical)
    log("thumbnail", f"thumb_vertical.png ready (portrait) -> {thumb_vertical}")
    _compose_portrait(base_image, word, "wide", config, thumb_wide)
    log("thumbnail", f"thumb_wide.png ready (portrait) -> {thumb_wide}")
    return {"vertical": thumb_vertical, "wide": thumb_wide}


# --------------------------------------------------------------------------
# Title mode (legacy): hero scene + wrapped title + corner mascot
# --------------------------------------------------------------------------

def _build_title(episode: dict, config: dict, paths: EpisodePaths,
                 thumb_vertical: Path, thumb_wide: Path) -> dict:
    from PIL import Image

    thumb_cfg = config["thumbnail"]
    scene_name = episode.get("thumbnail_scene") or thumb_cfg["hero_scene_default"]
    scene_path = paths.scenes_dir / f"{scene_name}.png"
    if not scene_path.exists():
        raise FileNotFoundError(f"hero scene not found for thumbnail: {scene_path}")
    scene_image = Image.open(scene_path).convert("RGB")
    mascot_rgba = _knockout_mascot(_mascot_reference())

    title = episode.get("thumbnail_title") or episode.get("title") or episode.get("topic") or "History"
    title_words = pick_title_words(title, thumb_cfg["title"])
    accent_index = pick_accent_index(title_words)
    log("thumbnail", f"title words: {' '.join(title_words)} (accent='{title_words[accent_index]}')")
    log("thumbnail", f"hero scene: {scene_path.name}")

    _compose_thumbnail(scene_image, mascot_rgba, title_words, accent_index, "vertical", config, thumb_vertical)
    log("thumbnail", f"thumb_vertical.png ready (title) -> {thumb_vertical}")
    _compose_thumbnail(scene_image, mascot_rgba, title_words, accent_index, "wide", config, thumb_wide)
    log("thumbnail", f"thumb_wide.png ready (title) -> {thumb_wide}")
    return {"vertical": thumb_vertical, "wide": thumb_wide}


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def build_thumbnails(episode_dir: Path, config: dict, force: bool = False) -> dict:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    thumb_vertical = paths.out_dir / "thumb_vertical.png"
    thumb_wide = paths.out_dir / "thumb_wide.png"

    if thumb_vertical.exists() and thumb_wide.exists() and not force:
        log("thumbnail", f"both thumbnails exist, skipping ({thumb_vertical}, {thumb_wide})")
        return {"vertical": thumb_vertical, "wide": thumb_wide}

    episode = read_json(paths.episode_json)
    thumb_cfg = config["thumbnail"]
    mode = str(episode.get("thumbnail_mode") or thumb_cfg.get("mode", "portrait")).lower()

    if mode == "portrait":
        try:
            return _build_portrait(episode, config, paths, thumb_vertical, thumb_wide, force)
        except Exception as error:  # noqa: BLE001 - portrait is nice-to-have, never block
            log("thumbnail", "!!! ==================================================================")
            log("thumbnail", f"!!! portrait thumbnail failed ({error}); falling back to title mode")
            log("thumbnail", "!!! ==================================================================")

    return _build_title(episode, config, paths, thumb_vertical, thumb_wide)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build vertical + wide clickable thumbnails")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="rebuild even if thumbnails exist")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    outputs = build_thumbnails(Path(args.episode), load_config(), force=args.force)
    for kind, path in outputs.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
