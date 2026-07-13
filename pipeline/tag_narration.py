"""Insert ElevenLabs v3 emotion audio tags into an episode's narration.

Reads episode.json "narration", asks `claude -p` to sprinkle SPARSE audio tags
([whispers] [excited] [pause] [sighs] [ominous] [building] [laughs]) that serve
the story arc, and writes the result back as "narration_tagged". The model may
ONLY add bracketed tags: it must not change, add, or remove a single word.

That invariant is enforced mechanically: strip every [...] tag and collapse
whitespace, and the result must equal the original narration byte-for-byte. On
mismatch we retry claude once, then fail loudly. tts.py (engine=elevenlabs)
prefers narration_tagged and falls back to plain narration if it is absent.

Standalone:  python tag_narration.py --episode ../episodes/ep021-usa-beat-england-1950
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import EpisodePaths, load_config, log, read_json, write_json
from generate_script import _call_claude

TAG_RE = re.compile(r"\[[^\]]*\]")
ALLOWED_TAGS = ["whispers", "excited", "pause", "sighs", "ominous", "building", "laughs"]


def _normalize(text: str) -> str:
    """Whitespace-insensitive comparison key."""
    return " ".join(text.split())


def _strip_tags(text: str) -> str:
    """Remove every [...] tag, then normalize whitespace. This is the exact
    inverse the validator checks: tags-only edits reconstruct the original."""
    return _normalize(TAG_RE.sub("", text))


def _extract_tagged(raw: str) -> str:
    """Pull the tagged narration out of a claude reply, tolerating stray fences
    or a leading label line while keeping the narration's own punctuation."""
    text = raw.strip()
    fenced = re.search(r"```(?:\w+)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    return text.strip()


def _build_prompt(narration: str) -> str:
    tag_list = ", ".join(f"[{t}]" for t in ALLOWED_TAGS)
    return (
        "You are an audio director for an ElevenLabs v3 text-to-speech voiceover of a "
        "60-second history YouTube Short. Insert SPARSE emotion audio tags into the "
        "narration below so the delivery follows the story arc.\n\n"
        f"ALLOWED TAGS (use ONLY these, in square brackets): {tag_list}.\n\n"
        "RULES (follow exactly):\n"
        "1. You may ONLY insert bracketed tags. Do NOT change, add, remove, reorder, or "
        "re-spell a single word. Do NOT alter punctuation. Every original word must remain, "
        "in the same order, spelled identically.\n"
        "2. Be sparse: at most 1-2 tags per sentence, and only where they earn their place. "
        "Most sentences get zero tags.\n"
        "3. Serve the arc: the hook = intrigue ([building] or [whispers]); the reveal / goal "
        "moment = excitement ([excited]); the punchline / final line = deadpan or mic-drop "
        "(a [pause] before it, not overt emotion).\n"
        "4. Place a tag immediately before the words it colours, e.g. \"[excited] One to nothing.\"\n"
        "5. Output ONLY the tagged narration as a single paragraph. No commentary, no quotes, "
        "no markdown fences, no labels.\n\n"
        f"NARRATION:\n{narration}"
    )


def _attempt(narration: str) -> tuple[str, bool]:
    """One claude round-trip. Returns (tagged_text, is_valid)."""
    raw = _call_claude(_build_prompt(narration))
    tagged = _extract_tagged(raw)
    return tagged, _strip_tags(tagged) == _normalize(narration)


def tag_episode(episode_dir: Path, config: dict, force: bool = False) -> Path:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    episode = read_json(paths.episode_json)
    narration = str(episode.get("narration", "")).strip()
    if not narration:
        raise ValueError("episode.json has empty narration; run generate_script first")

    if episode.get("narration_tagged") and not force:
        log("tag", f"narration_tagged already present, skipping ({paths.episode_json})")
        return paths.episode_json

    tagged = ""
    valid = False
    for attempt in range(1, 3):  # original try + one retry
        try:
            tagged, valid = _attempt(narration)
        except Exception as error:  # noqa: BLE001 - surface a clear message below
            log("tag", f"claude attempt {attempt}/2 errored ({error})")
            continue
        tag_count = len(TAG_RE.findall(tagged))
        if valid:
            log("tag", f"attempt {attempt}/2 valid: {tag_count} tags inserted")
            break
        log("tag", f"attempt {attempt}/2 changed the words (tags-only invariant broken); retrying")

    if not valid:
        raise RuntimeError(
            "tag_narration failed: claude did not return a tags-only edit after 2 attempts "
            "(stripping [tags] + normalizing whitespace did not reproduce the original "
            "narration). The narration was left untouched; rerun to retry."
        )

    updated = {**episode, "narration_tagged": tagged}
    write_json(paths.episode_json, updated)
    tag_count = len(TAG_RE.findall(tagged))
    log("tag", f"wrote narration_tagged into {paths.episode_json} ({tag_count} tags)")
    return paths.episode_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Insert ElevenLabs v3 audio tags into narration")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="re-tag even if narration_tagged exists")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    tag_episode(Path(args.episode), load_config(), force=args.force)


if __name__ == "__main__":
    main()
