"""Stage 3: voice.mp3 -> words.json (word-level timestamps) via faster-whisper.

We already know the script, so this is alignment: transcribe the clean TTS
audio with word timestamps on the small int8 CPU model. If faster-whisper is
unavailable or errors, fall back to an even split of the known narration across
the measured audio duration so karaoke captions still render.

Standalone:  python align.py --episode ../episodes/ep001-shortest-war
Via run.py:  align(episode_dir, config)
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import (
    EpisodePaths,
    audio_duration_seconds,
    load_config,
    log,
    read_json,
    write_json,
)


def _faster_whisper_words(audio_path: Path) -> list[dict]:
    from faster_whisper import WhisperModel  # lazy import

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    words: list[dict] = []
    for segment in segments:
        for word in (segment.words or []):
            token = word.word.strip()
            if not token:
                continue
            words.append({
                "word": token,
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3),
            })
    if not words:
        raise RuntimeError("faster-whisper returned no words")
    return words


def _even_split_words(narration: str, duration: float) -> list[dict]:
    tokens = re.findall(r"\S+", narration)
    if not tokens:
        return []
    step = duration / len(tokens)
    return [
        {
            "word": token,
            "start": round(i * step, 3),
            "end": round((i + 1) * step, 3),
        }
        for i, token in enumerate(tokens)
    ]


def align(episode_dir: Path, config: dict, force: bool = False) -> Path:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    if paths.words_json.exists():
        existing = read_json(paths.words_json)
        # The elevenlabs tts stage builds words.json directly from character-level
        # timestamps. Never re-run whisper over it (even with --force): the API
        # timing is authoritative and re-aligning would only degrade it.
        if str(existing.get("source", "")).startswith("elevenlabs"):
            log("align", "skipped: timestamps from elevenlabs")
            return paths.words_json
        if not force:
            log("align", f"words.json exists, skipping ({paths.words_json})")
            return paths.words_json

    if not paths.voice_mp3.exists():
        raise FileNotFoundError("voice.mp3 missing; run tts first")

    duration = audio_duration_seconds(paths.voice_mp3)
    episode = read_json(paths.episode_json)
    source = "faster-whisper"
    try:
        words = _faster_whisper_words(paths.voice_mp3)
    except Exception as error:  # noqa: BLE001 - degrade gracefully, keep captions
        log("align", f"faster-whisper failed ({error}); trying edge-tts cues")
        cues_path = paths.root / "voice.cues.json"
        words = []
        if cues_path.exists():
            cues = read_json(cues_path).get("words", [])
            words = [w for w in cues if w.get("word")]
        if words:
            source = "edge-tts-cues"
        else:
            log("align", "no edge-tts cues; using even-split fallback")
            source = "even-split"
            words = _even_split_words(episode.get("narration", ""), duration)

    if not words:
        raise RuntimeError("alignment produced no words and no narration to split")

    write_json(paths.words_json, {
        "audio_duration": round(duration, 3),
        "source": source,
        "word_count": len(words),
        "words": words,
    })
    log("align", f"wrote {paths.words_json} (source={source}, {len(words)} words, {duration:.1f}s)")
    return paths.words_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Align narration audio to word timestamps")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="re-align even if words.json exists")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    align(Path(args.episode), load_config(), force=args.force)


if __name__ == "__main__":
    main()
