"""Orchestrator: topic in -> final.mp4 out.

Runs every stage in order. Each stage is resumable: it skips work whose output
already exists (unless --force), so a crashed run continues where it stopped.

    python run.py --topic "The shortest war in history lasted 38 minutes" \
        --slug ep001-shortest-war

    python run.py --episode ../episodes/ep001-shortest-war --topic "..."   # explicit dir
    python run.py ... --no-codex     # placeholders only (fast iteration)
    python run.py ... --force        # rebuild every stage
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import align as align_stage
import animate as animate_stage
import generate_script as script_stage
import layers as layers_stage
import mascot_poses as mascot_poses_stage
import scenes as scenes_stage
import sfx as sfx_stage
import thumbnail as thumbnail_stage
import tts as tts_stage
from mascot_util import knockout_background
from common import (
    EpisodePaths,
    PIPELINE_DIR,
    PROJECT_DIR,
    audio_duration_seconds,
    load_config,
    log,
    read_json,
)
from thumbnail import pick_thumbnail_word, pick_title_words

REMOTION_DIR = PIPELINE_DIR / "remotion"
REMOTION_BIN = REMOTION_DIR / "node_modules" / ".bin" / "remotion"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "episode"


def _resolve_mascot() -> Path:
    mascot_dir = PROJECT_DIR / "assets" / "mascot"
    for name in ("mascot.png", "character.png", "raccoon-test.png", "raccoon.png"):
        candidate = mascot_dir / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No mascot PNG found in {mascot_dir} (expected mascot.png or character.png)"
    )


def _optional_mascot_frame(filename: str) -> Path | None:
    """A talking / blink frame is optional: return its path if it exists, else
    None so the render stays a plain static mascot."""
    candidate = PROJECT_DIR / "assets" / "mascot" / filename
    return candidate if candidate.exists() else None


def _paint_half_mouth(closed_path: Path, open_path: Path, dst: Path) -> bool:
    """Synthesise a half-open mouth by blending the open mouth region halfway into
    the closed frame, so the talking flap becomes closed->half->open->half. The
    mouth region is found automatically from the closed/open difference, so this
    works for any mascot art. Writes nothing (returns False) if it cannot locate
    a mouth, keeping the pipeline safe."""
    try:
        from PIL import Image, ImageChops

        closed = Image.open(closed_path).convert("RGB")
        opened = Image.open(open_path).convert("RGB")
        if closed.size != opened.size:
            opened = opened.resize(closed.size)
        diff = ImageChops.difference(closed, opened).convert("L")
        mask = diff.point(lambda value: 255 if value > 40 else 0)
        box = mask.getbbox()
        if box is None:
            return False
        pad = 10
        region = (
            max(0, box[0] - pad),
            max(0, box[1] - pad),
            min(closed.width, box[2] + pad),
            min(closed.height, box[3] + pad),
        )
        half = closed.copy()
        half.paste(Image.blend(closed.crop(region), opened.crop(region), 0.5), region)
        half.save(dst)
        return True
    except Exception as error:  # noqa: BLE001 - never block the render on this
        log("assemble", f"half-mouth paint skipped ({error})")
        return False


def _ensure_mascot_half() -> Path | None:
    """Half-open mouth asset. Painted once from the closed + open frames and reused
    thereafter. Returns its path, or None when there is no open frame to blend
    (the mascot then simply flaps closed<->open)."""
    half = PROJECT_DIR / "assets" / "mascot" / "mascot-talk-half.png"
    if half.exists():
        return half
    opened = _optional_mascot_frame("mascot-talk-open.png")
    if opened is None:
        return None
    return half if _paint_half_mouth(_resolve_mascot(), opened, half) else None


def _avg_hex(scene_png: Path) -> str:
    """A light, scene-tinted colour for particles / rays: the scene's average
    colour blended toward a warm white so motes stay visible. Falls back to a
    warm neutral if the image cannot be read."""
    warm = (255, 236, 204)
    try:
        from PIL import Image

        pixel = Image.open(scene_png).convert("RGB").resize((1, 1)).getpixel((0, 0))
        blended = tuple(round(pixel[i] * 0.4 + warm[i] * 0.6) for i in range(3))
        return "#%02x%02x%02x" % blended
    except Exception as error:  # noqa: BLE001
        log("assemble", f"tint sample skipped for {scene_png.name} ({error})")
        return "#c8a878"


def _scene_video_mode(episode: dict, index: int) -> str:
    """'playonce' for the first-last-frame hero clip (a one-way action that must
    NOT boomerang), else 'boomerang' for the ambient i2v loop clips."""
    hero_mode = str(episode.get("hero_mode", "")).strip().lower()
    hero_scene = episode.get("hero_scene")
    if hero_mode == "flf" and isinstance(hero_scene, int) and not isinstance(hero_scene, bool):
        if index == hero_scene:
            return "playonce"
    return "boomerang"


def _stage_scene_video(
    paths: EpisodePaths, render_dir: Path, index: int, episode: dict
) -> dict | None:
    """Stage scene_N_video.mp4 (if animate.py produced it) into the render dir and
    return {src, durationInSeconds, mode, stillSrc} for Remotion, else None so the
    scene stays stills. A clip that cannot be probed is ignored (never blocks)."""
    clip = paths.scenes_dir / f"scene_{index}_video.mp4"
    if not clip.exists():
        return None
    try:
        duration = audio_duration_seconds(clip)  # ffprobe format=duration (works for video)
    except Exception as error:  # noqa: BLE001 - unreadable clip -> fall back to stills
        log("assemble", f"scene_{index}_video.mp4 unreadable ({error}); using stills")
        return None
    shutil.copyfile(clip, render_dir / f"scene_{index}_video.mp4")
    mode = _scene_video_mode(episode, index)
    log("assemble", f"scene_{index}: hero video staged ({duration:.2f}s, mode={mode})")
    return {
        "src": f"render/scene_{index}_video.mp4",
        "durationInSeconds": round(duration, 3),
        "mode": mode,
        "stillSrc": f"render/scene_{index}.png",
    }


def _motion_props(config: dict) -> dict:
    """Map the snake_case config.json 'motion' section to the camelCase shape the
    Remotion props expect. Defaults keep the pack fully on and subtle."""
    motion = config.get("motion", {})
    parallax = motion.get("parallax", {})
    transitions = motion.get("transitions", {})
    effects = motion.get("effects", {})
    shake = motion.get("shake", {})
    captions = motion.get("captions", {})
    mascot = motion.get("mascot", {})
    shots = motion.get("shots", {})
    hook = motion.get("hook", {})
    emphasis = motion.get("emphasis", {})
    return {
        # Style profile selector. Remotion (motionStyle.ts) resolves the punchy
        # baseline below into the smooth (or punchy) curves; run.py only forwards
        # the chosen style and the baseline amplitudes.
        "style": motion.get("style", "smooth"),
        "parallax": {
            "enable": parallax.get("enable", True),
            "bgScale": parallax.get("bg_scale", 1.08),
            "bgDriftPx": parallax.get("bg_drift_px", 16),
            "fgDriftMultiplier": parallax.get("fg_drift_multiplier", 2.7),
            "fgZoomPct": parallax.get("fg_zoom_pct", 1.5),
        },
        "transitions": {
            "enable": transitions.get("enable", True),
            "frames": transitions.get("frames", 12),
            "cellPx": transitions.get("cell_px", 24),
        },
        "effects": {
            "enable": effects.get("enable", True),
            "particlesCount": effects.get("particles_count", 16),
            "particleSizePx": effects.get("particle_size_px", 3),
            "rayCount": effects.get("ray_count", 3),
            "vignetteStrength": effects.get("vignette_strength", 0.38),
            "tempSwayPct": effects.get("temp_sway_pct", 3),
        },
        "shake": {
            "enable": shake.get("enable", True),
            "px": shake.get("px", 4),
            "frames": shake.get("frames", 2),
            "sentenceGapSeconds": shake.get("sentence_gap_seconds", 0.5),
        },
        "captions": {
            "popScale": captions.get("pop_scale", 1.12),
            "settleScale": captions.get("settle_scale", 1.06),
            "entrancePx": captions.get("entrance_px", 8),
            "entranceFrames": captions.get("entrance_frames", 3),
        },
        "mascot": {
            "flapHz": mascot.get("flap_hz", 7),
            "leanDeg": mascot.get("lean_deg", 2),
            "squashPct": mascot.get("squash_pct", 3),
            "breathPct": mascot.get("breath_pct", 1),
            "entranceFrames": mascot.get("entrance_frames", 21),
        },
        "shots": {
            "enable": shots.get("enable", True),
            "minSeconds": shots.get("min_seconds", 3),
            "maxSeconds": shots.get("max_seconds", 5),
            "detailZoomMin": shots.get("detail_zoom_min", 1.35),
            "detailZoomMax": shots.get("detail_zoom_max", 1.5),
            "altZoomMin": shots.get("alt_zoom_min", 1.15),
            "altZoomMax": shots.get("alt_zoom_max", 1.25),
            "wideZoom": shots.get("wide_zoom", 1.08),
            "pushPct": shots.get("push_pct", 0.06),
            "driftPct": shots.get("drift_pct", 3),
            "maxZoom": shots.get("max_zoom", 1.6),
        },
        "hook": {
            "enable": hook.get("enable", True),
            "cardInFrame": hook.get("card_in_frame", 2),
            "cardHoldFrame": hook.get("card_hold_frame", 12),
            "cardOutFrame": hook.get("card_out_frame", 30),
            "punchFrame": hook.get("punch_frame", 36),
            "punchScale": hook.get("punch_scale", 1.18),
            "headStartFrac": hook.get("head_start_frac", 0.15),
            "cardFontPx": hook.get("card_font_px", 150),
        },
        "emphasis": {
            "enable": emphasis.get("enable", True),
            "fontSizePx": emphasis.get("font_size_px", 140),
            "yPct": emphasis.get("y_pct", 33),
            "holdFrames": emphasis.get("hold_frames", 12),
            "color": emphasis.get("color", "#ffe14d"),
            "outlineColor": emphasis.get("outline_color", "#000000"),
            "outlinePx": emphasis.get("outline_px", 12),
        },
    }


def _scene_effect_hints(episode: dict, scene_count: int) -> list | None:
    """Optional per-scene effect override from episode.json 'motion' (a list of
    'particles' / 'rays' / 'vignette'). Ignored unless it is a list of strings."""
    hint = episode.get("motion")
    if isinstance(hint, list) and all(isinstance(item, str) for item in hint):
        return list(hint[:scene_count])
    return None


def _episode_scene_count(episode: dict, config: dict) -> int:
    """Prefer the episode's real scene list when old 5-scene drafts do not carry
    an explicit scene_count. New bit-scene episodes keep their authored override."""
    explicit = episode.get("scene_count")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit > 0:
        return explicit
    scenes = episode.get("scenes")
    if isinstance(scenes, list) and scenes:
        return len(scenes)
    return int(config["video"]["scene_count"])


def _stage_sfx(render_dir: Path, config: dict) -> dict | None:
    """Synthesize (idempotent) the 8-bit SFX pack, copy the WAVs into the render
    dir, and build the sfx prop with per-type gains. Returns None (render stays
    sfx-free, never fails) when SFX are disabled or unavailable."""
    sfx_cfg = config.get("sfx", {})
    if not sfx_cfg.get("enable", True):
        return None
    try:
        paths = sfx_stage.synthesize(config)
    except Exception as error:  # noqa: BLE001 - SFX are enhancement, never block
        log("sfx", f"synthesis unavailable ({error}); rendering without sfx")
        return None

    sfx_dir = render_dir / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)
    staged: dict[str, str] = {}
    for name, src in paths.items():
        if not src.exists():
            log("sfx", f"missing {name}.wav after synthesis; rendering without sfx")
            return None
        shutil.copyfile(src, sfx_dir / f"{name}.wav")
        staged[name] = f"render/sfx/{name}.wav"

    gains = sfx_cfg.get("gains", {})
    return {
        "masterGain": sfx_cfg.get("master_gain", 0.35),
        "gains": {
            "whoosh": gains.get("whoosh", 0.5),
            "impact": gains.get("impact", 0.7),
            "riser": gains.get("riser", 0.4),
            "blip": gains.get("blip", 0.6),
            "pop": gains.get("pop", 0.55),
        },
        "whooshUp": staged["whoosh_up"],
        "whooshDown": staged["whoosh_down"],
        "impact": staged["impact"],
        "riser": staged["riser"],
        "blip": staged["blip"],
        "pop": staged["pop"],
    }


def _stage_preview(
    paths: EpisodePaths, render_dir: Path, episode: dict, config: dict
) -> tuple[str | None, str]:
    """Stage the cold-open PREVIEW card: the baked thumbnail portrait
    (out/thumb_portrait_base.png) plus the burned thumbnail word. When the
    portrait exists it becomes the first beat (a full-screen preview that replaces
    the text-only hook card). Null-safe: no portrait -> (None, "") so Remotion
    falls back to the old text card."""
    base = paths.out_dir / "thumb_portrait_base.png"
    if not base.exists():
        log("assemble", "no thumb_portrait_base.png -> cold-open falls back to text hook card")
        return None, ""
    shutil.copyfile(base, render_dir / "preview_base.png")
    try:
        word = pick_thumbnail_word(episode, config["thumbnail"]["title"])
    except Exception as error:  # noqa: BLE001 - preview word is optional, never block
        log("assemble", f"preview word unavailable ({error}); using topic tail")
        word = ""
    log("assemble", f"cold-open preview staged (word='{word}')")
    return "render/preview_base.png", word


def _hook_words(episode: dict, config: dict) -> list[str]:
    """2-3 punchy uppercase words for the cold-open card, reusing the thumbnail
    title-word logic (the tail carries the payload)."""
    title = episode.get("title") or episode.get("topic") or ""
    title_cfg = config.get("thumbnail", {}).get("title", {})
    try:
        words = pick_title_words(title, title_cfg)
    except Exception as error:  # noqa: BLE001 - card is optional, never block
        log("assemble", f"hook words unavailable ({error})")
        return []
    return words[-3:] if len(words) > 3 else words


_EMPHASIS_STRIP_RE = re.compile(r"^[^\w']+|[^\w']+$", re.UNICODE)
_SENTENCE_OPENERS = {
    "the", "it", "they", "then", "these", "those", "nobody", "one", "a", "an",
    "and", "but", "so", "he", "she", "his", "her", "their", "its", "this",
    "that", "in", "on", "at", "for", "with", "as", "by", "there", "here",
}


def _clean_token(token: str) -> str:
    return _EMPHASIS_STRIP_RE.sub("", token)


def _emphasis_pops(episode: dict, words_data: dict, config: dict) -> list[dict]:
    """3-6 keyword pops. Uses episode.json 'emphasis' if present, else falls back
    to numbers/years (priority) then the longest proper nouns at sentence starts,
    enforcing a minimum spacing so pops never crowd each other."""
    emph_cfg = config.get("motion", {}).get("emphasis", {})
    if not emph_cfg.get("enable", True):
        return []
    words = words_data.get("words", [])
    if not words:
        return []

    max_pops = int(emph_cfg.get("max_pops", 5))
    min_spacing = float(emph_cfg.get("min_spacing_seconds", 8.0))
    gap = config.get("motion", {}).get("shake", {}).get("sentence_gap_seconds", 0.5)

    candidates: list[tuple[str, float]] = []  # already in priority order
    explicit = episode.get("emphasis")
    if isinstance(explicit, list) and explicit:
        wanted = [str(item).strip().lower() for item in explicit if str(item).strip()]
        used: set[int] = set()
        for target in wanted:
            for i, word in enumerate(words):
                if i in used:
                    continue
                token = _clean_token(word["word"])
                if token.lower() == target:
                    candidates.append((token.upper(), float(word["start"])))
                    used.add(i)
                    break
    else:
        # A number qualifies only with 2+ digits (drop bare single-digit picks like
        # "1"/"0"); proper nouns still need length >= 4 (enforced below).
        numbers = [
            (_clean_token(w["word"]).upper(), float(w["start"]))
            for w in words
            if sum(c.isdigit() for c in w["word"]) >= 2 and _clean_token(w["word"])
        ]
        numbers.sort(key=lambda pair: pair[1])
        propers: list[tuple[str, float, int]] = []
        for i, word in enumerate(words):
            is_start = i == 0 or (word["start"] - words[i - 1]["end"] > gap)
            if not is_start:
                continue
            token = _clean_token(word["word"])
            if len(token) < 4 or not token[0].isupper() or any(c.isdigit() for c in token):
                continue
            if token.lower() in _SENTENCE_OPENERS:
                continue
            propers.append((token.upper(), float(word["start"]), len(token)))
        propers.sort(key=lambda triple: -triple[2])
        candidates = [(tok, start) for tok, start in numbers]
        candidates += [(tok, start) for tok, start, _length in propers]

    accepted: list[tuple[str, float]] = []
    for token, start in candidates:
        if len(accepted) >= max_pops:
            break
        if all(abs(start - other) >= min_spacing for _tok, other in accepted):
            accepted.append((token, start))
    accepted.sort(key=lambda pair: pair[1])
    return [{"word": token, "start": round(start, 3)} for token, start in accepted]


_ALNUM_RE = re.compile(r"[^\w]+", re.UNICODE)
_CALLOUT_STYLES = frozenset({"scoreboard", "label", "shock"})
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _callout_spans(item: dict) -> list[dict] | None:
    """Soft-validate an optional per-segment colour list on a callout: a list of
    {text, color} where color is a #rrggbb hex. Any malformed entry drops the
    whole spans list (the callout falls back to its flat `text`), never fatal."""
    raw = item.get("spans")
    if not isinstance(raw, list) or not raw:
        return None
    spans: list[dict] = []
    for span in raw:
        if not isinstance(span, dict):
            return None
        text = span.get("text")
        color = span.get("color")
        if not isinstance(text, str) or not text:
            return None
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            return None
        spans.append({"text": text, "color": color})
    return spans


def _normalize_token(token: str) -> str:
    """Lowercase and strip punctuation for robust anchors in any script language."""
    return _ALNUM_RE.sub("", token.lower())


def _caption_emphasis_words(episode: dict) -> list[str]:
    """Normalized (lowercase, alnum-only) words the single-word captions paint in
    the accent colour. Sourced from episode.json 'emphasis' (numbers are accented
    automatically in Captions.tsx, so they need not be listed)."""
    explicit = episode.get("emphasis")
    if not isinstance(explicit, list):
        return []
    seen: list[str] = []
    for item in explicit:
        norm = _normalize_token(str(item))
        if norm and norm not in seen:
            seen.append(norm)
    return seen


def _find_subsequence(
    norm_words: list[str], needle: list[str], start_index: int = 0, occurrence: int = 1
) -> int | None:
    """Index of the occurrence-th contiguous run of `needle` in `norm_words` at or
    after start_index, else None. Matching a short RUN (not one word) disambiguates
    common openers like 'the'."""
    if not needle:
        return None
    span = len(needle)
    found = 0
    for i in range(start_index, len(norm_words) - span + 1):
        if norm_words[i : i + span] == needle:
            found += 1
            if found >= occurrence:
                return i
    return None


def _scene_starts(episode: dict, words_data: dict, config: dict) -> list[float] | None:
    """Per-scene narration start SECONDS so scenes cut exactly where their line
    begins. Maps each timeline[].vo's opening words onto words.json timestamps
    (normalized, sequential contiguous scan). Returns None on ANY mismatch so
    Remotion falls back to the equal split. Scene 1 is forced to 0.0."""
    timeline = episode.get("timeline")
    words = words_data.get("words", [])
    scene_count = _episode_scene_count(episode, config)
    if not isinstance(timeline, list) or len(timeline) != scene_count or not words:
        return None
    if not all(isinstance(entry, dict) for entry in timeline):
        return None
    norm_words = [_normalize_token(w["word"]) for w in words]
    ordered = sorted(timeline, key=lambda entry: entry.get("scene", 0))
    starts: list[float] = []
    cursor = 0
    for entry in ordered:
        head = [tok for tok in (_normalize_token(t) for t in str(entry.get("vo", "")).split()) if tok][:3]
        if not head:
            return None
        index = _find_subsequence(norm_words, head, cursor)
        if index is None:
            return None
        starts.append(float(words[index]["start"]))
        cursor = index + 1
    if starts != sorted(starts):  # must be non-decreasing in time
        return None
    starts[0] = 0.0
    return starts


def _callouts(episode: dict, words_data: dict, config: dict) -> list[dict]:
    """Resolve episode.json 'callouts' anchors to composition frames. Each anchor is
    matched verbatim (normalized, contiguous run) against words.json; 'occurrence'
    (1-based, default 1) disambiguates repeats. An anchor that cannot be found is
    skipped with a warning (never fatal). Returns [{frame, text, style}] by frame."""
    raw = episode.get("callouts")
    if not isinstance(raw, list) or not raw:
        return []
    words = words_data.get("words", [])
    if not words:
        return []
    fps = int(config["video"]["fps"])
    norm_words = [_normalize_token(w["word"]) for w in words]
    resolved: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        anchor = str(item.get("anchor", "")).strip()
        text = str(item.get("text", "")).strip()
        style = str(item.get("style", "")).strip().lower()
        if not anchor or not text or style not in _CALLOUT_STYLES:
            log("assemble", f"callout skipped (bad anchor/text/style): {item!r}")
            continue
        occurrence = item.get("occurrence", 1)
        if not (isinstance(occurrence, int) and not isinstance(occurrence, bool) and occurrence >= 1):
            occurrence = 1
        needle = [tok for tok in (_normalize_token(t) for t in anchor.split()) if tok]
        index = _find_subsequence(norm_words, needle, 0, occurrence)
        if index is None:
            log("assemble", f"callout anchor not found: {anchor!r} (occurrence {occurrence}); skipping")
            continue
        start = float(words[index]["start"])
        # Optional per-callout shift: lets an authored event card land AFTER its
        # narration anchor (e.g. the scoreline card waits for the on-screen goal).
        start += float(item.get("offset_s", 0.0) or 0.0)
        callout = {"frame": int(round(start * fps)), "text": text, "style": style}
        spans = _callout_spans(item)
        if spans is not None:
            callout["spans"] = spans
        resolved.append(callout)
    resolved.sort(key=lambda callout: callout["frame"])
    return resolved


def _prepare_mascot(src: Path, dst: Path) -> None:
    """Knock out the mascot's solid background to transparency (shared helper,
    also used by mascot_poses.py) so it sits cleanly on scenes. Never fails:
    the helper falls back to a plain copy on any error."""
    knockout_background(src, dst)


def _stage_mascot_poses(paths: EpisodePaths, render_dir: Path, scene_count: int) -> list[str | None]:
    """Stage the per-scene pose sprites (mascot_poses.py output, already
    background-knocked-out) into the render dir. Returns the mascotPoses prop:
    one src per scene, None where the scene keeps the base narrator sprite."""
    poses: list[str | None] = []
    for index in range(1, scene_count + 1):
        sprite = mascot_poses_stage.pose_sprite_path(paths.root, index)
        if sprite.exists():
            shutil.copyfile(sprite, render_dir / f"mascot_pose_{index}.png")
            poses.append(f"render/mascot_pose_{index}.png")
        else:
            poses.append(None)
    staged = sum(1 for pose in poses if pose is not None)
    if staged > 0:
        log("assemble", f"mascot pose pack staged ({staged}/{scene_count} scenes)")
    return poses


def _stage_assets(paths: EpisodePaths, config: dict) -> dict:
    """Copy episode assets into remotion/public/render and build inputProps."""
    render_dir = REMOTION_DIR / "public" / "render"
    if render_dir.exists():
        shutil.rmtree(render_dir)
    render_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(paths.voice_mp3, render_dir / "voice.mp3")

    # Optional corner narrator. It is disabled by default; when enabled the
    # renderer stages user-supplied sprite frames and remains null-safe.
    mascot_enabled = bool(config["mascot"].get("enable", True))
    mascot_src: str | None = None
    mascot_open_src: str | None = None
    mascot_blink_src: str | None = None
    mascot_half_src: str | None = None
    if mascot_enabled:
        _prepare_mascot(_resolve_mascot(), render_dir / "mascot.png")
        mascot_src = "render/mascot.png"

        # Optional talking / blink frames. Same background-knockout as the closed
        # mascot; missing files simply leave the render as a static sprite.
        open_frame = _optional_mascot_frame("mascot-talk-open.png")
        if open_frame is not None:
            _prepare_mascot(open_frame, render_dir / "mascot_open.png")
            mascot_open_src = "render/mascot_open.png"

        blink_frame = _optional_mascot_frame("mascot-blink.png")
        if blink_frame is not None:
            _prepare_mascot(blink_frame, render_dir / "mascot_blink.png")
            mascot_blink_src = "render/mascot_blink.png"

        # Half-open mouth for a smoother closed->half->open->half flap. Auto-painted
        # from the closed + open frames if the asset is not already present.
        half_frame = _ensure_mascot_half()
        if half_frame is not None:
            _prepare_mascot(half_frame, render_dir / "mascot_half.png")
            mascot_half_src = "render/mascot_half.png"

    words_data = read_json(paths.words_json)
    episode = read_json(paths.episode_json)

    # Per-episode override: kisa-format episodes carry ~20-25 bit-scenes while the
    # config default stays 5 for legacy episodes.
    scene_count = _episode_scene_count(episode, config)
    scene_srcs: list[str] = []
    # Parallax layers per scene: copy fg/bg when layers.py produced them, else None
    # so Remotion falls back to enhanced Ken Burns for that scene.
    layers_prop: list[dict | None] = []
    scene_tints: list[str] = []
    # Hero-scene video clips per scene: {src, durationInSeconds, mode, stillSrc} when
    # animate.py produced scene_N_video.mp4, else None so the scene renders as stills.
    scene_videos: list[dict | None] = []
    for index in range(1, scene_count + 1):
        src = paths.scenes_dir / f"scene_{index}.png"
        if not src.exists():
            raise FileNotFoundError(f"missing scene image: {src}")
        shutil.copyfile(src, render_dir / f"scene_{index}.png")
        scene_srcs.append(f"render/scene_{index}.png")
        scene_tints.append(_avg_hex(src))

        fg = paths.scenes_dir / f"scene_{index}_fg.png"
        bg = paths.scenes_dir / f"scene_{index}_bg.png"
        if fg.exists() and bg.exists():
            shutil.copyfile(fg, render_dir / f"scene_{index}_fg.png")
            shutil.copyfile(bg, render_dir / f"scene_{index}_bg.png")
            layers_prop.append(
                {"fg": f"render/scene_{index}_fg.png", "bg": f"render/scene_{index}_bg.png"}
            )
        else:
            layers_prop.append(None)

        scene_videos.append(_stage_scene_video(paths, render_dir, index, episode))

    # Subscribe end-card (kisa-style closer). Null-safe: disabled or missing
    # image -> no card, duration stays audio-based.
    end_card: dict | None = None
    endcard_cfg = config.get("endcard", {})
    if endcard_cfg.get("enable", False):
        card_image = (PROJECT_DIR / endcard_cfg.get("image", "assets/channel/avatar.png")).resolve()
        if card_image.exists():
            shutil.copyfile(card_image, render_dir / "endcard_mascot.png")
            voice_src: str | None = None
            card_voice = (PROJECT_DIR / endcard_cfg.get("voice", "assets/channel/endcard_voice.mp3")).resolve()
            if card_voice.exists():
                shutil.copyfile(card_voice, render_dir / "endcard_voice.mp3")
                voice_src = "render/endcard_voice.mp3"
            end_card = {
                "imageSrc": "render/endcard_mascot.png",
                "voiceSrc": voice_src,
                "seconds": float(endcard_cfg.get("seconds", 2.6)),
                "title": endcard_cfg.get("title", "RACCOON REWIND"),
                "subtitle": endcard_cfg.get("subtitle", "NEW STORY EVERY DAY"),
                "button": endcard_cfg.get("button", "SUBSCRIBE"),
            }
            log("assemble", f"end-card staged ({end_card['seconds']}s, voice={'yes' if voice_src else 'no'})")
        else:
            log("assemble", f"endcard image missing ({card_image}); skipping end-card")

    music_src: str | None = None
    music_file = (PROJECT_DIR / config["music"]["file"]).resolve()
    if config["music"].get("enabled", True) and music_file.exists():
        shutil.copyfile(music_file, render_dir / "track.mp3")
        music_src = "render/track.mp3"
    else:
        log("assemble", "no music file present -> rendering without music")

    caps = config["captions"]
    music_cfg = config["music"]
    sfx_prop = _stage_sfx(render_dir, config)
    preview_src, preview_word = _stage_preview(paths, render_dir, episode, config)
    # Authored story callouts are the headline layer when present; they replace the
    # emphasis-pops heuristic for this episode (older episodes keep the pops).
    callouts = _callouts(episode, words_data, config)
    emphasis_pops = [] if callouts else _emphasis_pops(episode, words_data, config)
    scene_starts = _scene_starts(episode, words_data, config)
    if callouts:
        log("assemble", f"story callouts: {len(callouts)} resolved -> {[c['frame'] for c in callouts]}")
    if scene_starts is not None:
        log("assemble", f"scene starts (s): {[round(s, 2) for s in scene_starts]}")
    return {
        "crf": config["video"].get("crf", 23),
        "fps": config["video"]["fps"],
        "width": config["video"]["width"],
        "height": config["video"]["height"],
        "audioDuration": words_data["audio_duration"],
        "audioSrc": "render/voice.mp3",
        "musicSrc": music_src,
        "musicVolume": music_cfg["music_volume"],
        "musicDuck": {
            "noSpeech": music_cfg.get("duck_no_speech", 0.35),
            "underSpeech": music_cfg.get("duck_under_speech", 0.15),
            "punchline": music_cfg.get("duck_punchline", 0.02),
        },
        "sfx": sfx_prop,
        "previewSrc": preview_src,
        "previewWord": preview_word,
        "hookWords": _hook_words(episode, config),
        "emphasisPops": emphasis_pops,
        "callouts": callouts,
        "sceneStarts": scene_starts,
        "mascotSrc": mascot_src,
        "mascotHalfSrc": mascot_half_src,
        "mascotOpenSrc": mascot_open_src,
        "mascotBlinkSrc": mascot_blink_src,
        "mascotSizePx": config["mascot"]["size_px"],
        "scenes": scene_srcs,
        "layers": layers_prop,
        "sceneVideos": scene_videos,
        "sceneTints": scene_tints,
        "sceneEffects": _scene_effect_hints(episode, scene_count),
        "endCard": end_card,
        "motion": _motion_props(config),
        "words": words_data["words"],
        "captions": {
            "wordsPerGroup": caps["words_per_group"],
            "fontSizePx": caps["font_size_px"],
            "bottomOffsetPx": caps["bottom_offset_px"],
            "position": caps.get("position", "bottom"),
            "topOffsetPx": caps.get("top_offset_px", 150),
            "activeColor": caps["active_color"],
            "idleColor": caps["idle_color"],
            "outlineColor": caps["outline_color"],
            "outlinePx": caps["outline_px"],
            "minDisplayFrames": caps.get("min_display_frames", 5),
            # Single-word captions are white by default; these explicit emphasis
            # words (+ any word with a digit, decided in Captions.tsx) go yellow.
            "emphasisWords": _caption_emphasis_words(episode),
        },
    }


def _render(paths: EpisodePaths, props: dict) -> Path:
    if not REMOTION_BIN.exists():
        raise FileNotFoundError(
            f"Remotion CLI not installed at {REMOTION_BIN}. Run `npm install` in {REMOTION_DIR}."
        )
    props_path = paths.out_dir / "props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

    command = [
        str(REMOTION_BIN), "render", "src/index.ts", "Short",
        str(paths.final_mp4),
        f"--props={props_path}",
        "--codec=h264",
        f"--crf={props['crf']}",
        "--log=info",
    ]
    log("assemble", f"rendering -> {paths.final_mp4}")
    env = os.environ.copy()
    result = subprocess.run(command, cwd=str(REMOTION_DIR), env=env)
    if result.returncode != 0:
        raise RuntimeError(f"remotion render exited {result.returncode}")
    if not paths.final_mp4.exists():
        raise RuntimeError("remotion render reported success but final.mp4 is missing")
    return paths.final_mp4


def assemble(episode_dir: Path, config: dict, force: bool = False) -> Path:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    if paths.final_mp4.exists() and not force:
        log("assemble", f"final.mp4 exists, skipping ({paths.final_mp4})")
        return paths.final_mp4
    props = _stage_assets(paths, config)
    return _render(paths, props)


def _probe(final_mp4: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(final_mp4)],
        capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def _with_codex_budget(config: dict, budget: int) -> dict:
    adapter = {**config["scenes_adapter"], "codex_scene_budget": budget}
    return {**config, "scenes_adapter": adapter}


def _safe_layers(episode_dir: Path, config: dict, force: bool) -> None:
    """Run the optional parallax-layer stage without ever failing the pipeline."""
    try:
        layers_stage.build_layers(episode_dir, config, force=force)
    except Exception as error:  # noqa: BLE001 - fall back to Ken Burns, keep going
        log("layers", f"stage failed ({error}); continuing with Ken Burns fallback")


def _safe_animate(episode_dir: Path, config: dict, force: bool) -> None:
    """Run the optional hero-scene i2v stage without ever failing the pipeline. A
    missing/errored clip simply leaves the scene as animated stills."""
    try:
        animate_stage.animate(episode_dir, config, force=force)
    except Exception as error:  # noqa: BLE001 - fall back to stills, keep going
        log("animate", f"stage failed ({error}); continuing with still scenes")



def _embed_cover(episode_dir: Path) -> None:
    """Embed thumb_vertical.png into final.mp4 as an attached_pic cover stream.
    Players and upload UIs then show a real preview for the file. Atomic
    (tmp + rename) and never fails the pipeline."""
    out_dir = episode_dir / "out"
    final = out_dir / "final.mp4"
    thumb = out_dir / "thumb_vertical.png"
    if not final.exists() or not thumb.exists():
        return
    tmp = out_dir / "final.cover.tmp.mp4"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(final), "-i", str(thumb),
        "-map", "0", "-map", "1",
        "-c", "copy", "-disposition:v:1", "attached_pic",
        str(tmp),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[:200] or "ffmpeg failed")
        tmp.replace(final)
        log("cover", "embedded thumb_vertical.png as attached_pic cover")
    except Exception as error:  # noqa: BLE001 - cover art is nice-to-have, never block
        tmp.unlink(missing_ok=True)
        log("cover", f"cover embed failed ({error}); final.mp4 left as-is")

def _safe_thumbnail(episode_dir: Path, config: dict, force: bool) -> None:
    """Run the optional thumbnail stage without ever failing the pipeline. Nice
    to have for the channel grid / long-form compilations, never worth blocking
    a finished Short over."""
    try:
        thumbnail_stage.build_thumbnails(episode_dir, config, force=force)
    except Exception as error:  # noqa: BLE001 - thumbnails are nice-to-have, never block
        log("thumbnail", f"stage failed ({error}); skipping thumbnails")


def _voice_postfx(episode_dir: Path, config: dict) -> None:
    """Voice polish pass: rumble removal + light compression + loudness control.
    Runs AFTER timestamps are captured (timing-safe: purely additive/level ops).
    Idempotent: the untouched original is kept as voice.prefx.mp3; its presence
    means the pass already ran. Never fails the pipeline."""
    if not config.get("voice", {}).get("postfx", {}).get("enable", False):
        return
    paths = EpisodePaths.for_dir(episode_dir)
    voice = paths.voice_mp3
    prefx = voice.with_name("voice.prefx.mp3")
    if not voice.exists() or prefx.exists():
        return
    tmp = voice.with_name("voice.postfx.tmp.mp3")
    chain = (
        "highpass=f=70,"
        "acompressor=threshold=-18dB:ratio=2:attack=15:release=160,"
        "loudnorm=I=-14:TP=-1.5:LRA=7"
    )
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(voice),
        "-af", chain, "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "2", str(tmp),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[:200] or "ffmpeg failed")
        shutil.copyfile(voice, prefx)
        tmp.replace(voice)
        log("tts", "voice postfx applied (high-pass + light compression + loudnorm)")
    except Exception as error:  # noqa: BLE001 - enhancement, never block
        tmp.unlink(missing_ok=True)
        log("tts", f"voice postfx skipped ({error})")


def _stage_tts(episode_dir: Path, config: dict, force: bool) -> None:
    """TTS with an engine-aware safety net. When voice.engine=elevenlabs and the
    API call fails (quota exhausted is the expected one), fall back to edge-tts
    with a LOUD warning so a paid-key hiccup never blocks a finished Short."""
    engine = str(config.get("voice", {}).get("engine", "edge-tts")).lower()
    if engine != "elevenlabs":
        tts_stage.synthesize(episode_dir, config, force=force)
        return
    try:
        tts_stage.synthesize(episode_dir, config, force=force)
    except Exception as error:  # noqa: BLE001 - degrade to edge-tts, never block the run
        log("tts", "!!! ==================================================================")
        log("tts", f"!!! ELEVENLABS TTS FAILED: {error}")
        log("tts", "!!! FALLING BACK TO edge-tts for this run.")
        log("tts", "!!! Fix: ElevenLabs dashboard -> API key -> credit quota (raise above 0).")
        log("tts", "!!! ==================================================================")
        edge_config = {**config, "voice": {**config["voice"], "engine": "edge-tts"}}
        # force=True: overwrite any partial artefact left by the elevenlabs attempt.
        tts_stage.synthesize(episode_dir, edge_config, force=True)


def run(topic: str, episode_dir: Path, config: dict, force: bool) -> Path:
    timings: dict[str, float] = {}

    def timed(name: str, fn) -> None:
        start = time.time()
        fn()
        timings[name] = round(time.time() - start, 1)
        log("run", f"stage '{name}' took {timings[name]}s")

    timed("script", lambda: script_stage.generate(episode_dir, topic, config, force=force))
    timed("tts", lambda: _stage_tts(episode_dir, config, force=force))
    timed("align", lambda: align_stage.align(episode_dir, config, force=force))
    # Anti-sterility audio pass AFTER alignment so word timings are captured from
    # the clean synth and whisper (edge-tts fallback path) never hears the room tone.
    timed("voice_postfx", lambda: _voice_postfx(episode_dir, config))
    timed("scenes", lambda: scenes_stage.render_scenes(episode_dir, config, force=force))
    # Optional parallax layers between scenes and assemble. Never fails the run:
    # a missing / errored layer simply falls back to enhanced Ken Burns.
    timed("layers", lambda: _safe_layers(episode_dir, config, force=force))
    # Optional hero-scene image-to-video (fal.ai). Needs the scene stills; runs
    # independently of layers. Cost-guarded and never fails the run: a missing /
    # errored clip leaves that scene as animated stills.
    timed("animate", lambda: _safe_animate(episode_dir, config, force=force))
    # 8-bit SFX pack (deterministic, idempotent). Must run before assemble so the
    # WAVs exist to be staged into the render dir and referenced in props.
    timed("sfx", lambda: sfx_stage.synthesize(config, force=force))
    timed("assemble", lambda: assemble(episode_dir, config, force=force))
    # Optional thumbnail stage: out/thumb_vertical.png + out/thumb_wide.png for
    # the channel grid and long-form compilations. Never fails the run.
    timed("thumbnail", lambda: _safe_thumbnail(episode_dir, config, force=force))
    timed("cover", lambda: _embed_cover(episode_dir))

    paths = EpisodePaths.for_dir(episode_dir)
    probe = _probe(paths.final_mp4)
    video = next((s for s in probe["streams"] if s["codec_type"] == "video"), {})
    audio = next((s for s in probe["streams"] if s["codec_type"] == "audio"), {})
    summary = {
        "final_mp4": str(paths.final_mp4),
        "duration_s": round(float(probe["format"]["duration"]), 2),
        "video_codec": video.get("codec_name"),
        "resolution": f"{video.get('width')}x{video.get('height')}",
        "audio_codec": audio.get("codec_name"),
        "size_mb": round(int(probe["format"]["size"]) / 1_048_576, 2),
        "stage_seconds": timings,
    }
    log("run", "DONE " + json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return paths.final_mp4


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the optional Agent Shorts Kit pipeline")
    parser.add_argument("--topic", required=True, help="episode topic / hook")
    parser.add_argument("--slug", help="episode folder name under episodes/ (default: from topic)")
    parser.add_argument("--episode", help="explicit episode directory (overrides --slug)")
    parser.add_argument("--no-codex", action="store_true", help="placeholders only, skip codex images")
    parser.add_argument("--force", action="store_true", help="rebuild every stage")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = load_config()
    if args.no_codex:
        config = _with_codex_budget(config, 0)
    if args.episode:
        episode_dir = Path(args.episode)
    else:
        slug = args.slug or _slugify(args.topic)
        episode_dir = PROJECT_DIR / "episodes" / slug
    run(args.topic, episode_dir, config, force=args.force)


if __name__ == "__main__":
    main()
