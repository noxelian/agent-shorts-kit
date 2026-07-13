"""Stage 2: narration text -> voice.mp3.

Two switchable engines, chosen by config.json voice.engine:

  edge-tts    (default) free MS neural voices. Streams synthesis and captures
              WordBoundary cues into voice.cues.json so align.py can build
              karaoke timings even without whisper.

  elevenlabs  ElevenLabs v3 with emotion audio tags. Calls the with-timestamps
              endpoint, decodes audio_base64 -> voice.mp3, and builds words.json
              DIRECTLY from the returned character timestamps (align.py then
              skips whisper). Prefers episode.json "narration_tagged" (audio
              tags), falls back to plain "narration". Any API failure (quota!)
              raises a clear error; run.py catches it and falls back to edge-tts.

Standalone:  python tts.py --episode ../episodes/ep021-usa-beat-england-1950
Via run.py:  synthesize(episode_dir, config)
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import el_align
import el_client
from common import (
    EpisodePaths,
    audio_duration_seconds,
    get_env,
    load_config,
    log,
    read_json,
    write_json,
)

# edge-tts WordBoundary offset/duration are in 100-nanosecond ticks.
TICKS_PER_SECOND = 10_000_000
SYNTH_TIMEOUT_S = 90
MAX_ATTEMPTS = 3


def synthesize(episode_dir: Path, config: dict, force: bool = False) -> Path:
    """Dispatch to the configured engine. Defaults to edge-tts."""
    engine = str(config.get("voice", {}).get("engine", "edge-tts")).lower()
    if engine == "elevenlabs":
        return _synthesize_elevenlabs(episode_dir, config, force)
    return _synthesize_edge(episode_dir, config, force)


# --------------------------------------------------------------------------- #
# ElevenLabs engine
# --------------------------------------------------------------------------- #
def _synthesize_elevenlabs(episode_dir: Path, config: dict, force: bool) -> Path:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()

    # Skip only when a previous elevenlabs run already produced BOTH artefacts.
    if not force and paths.voice_mp3.exists() and paths.words_json.exists():
        existing = read_json(paths.words_json)
        if str(existing.get("source", "")).startswith("elevenlabs"):
            log("tts", f"elevenlabs voice.mp3 + words.json exist, skipping ({paths.voice_mp3})")
            return paths.voice_mp3

    episode = read_json(paths.episode_json)
    tagged = str(episode.get("narration_tagged", "")).strip()
    plain = str(episode.get("narration", "")).strip()
    text = tagged or plain
    if not text:
        raise ValueError("episode.json has empty narration; run generate_script first")
    used_tagged = bool(tagged)

    el_cfg = config["voice"].get("elevenlabs", {})
    voice_id = el_cfg.get("voice_id")
    if not voice_id:
        raise ValueError("config.json voice.elevenlabs.voice_id is required for engine=elevenlabs")
    voice_name = el_cfg.get("voice_name", voice_id)
    model_chain = el_cfg.get("model_fallback") or [el_cfg.get("model_id", "eleven_v3")]
    api_key = get_env("ELEVENLABS_API_KEY")

    model_id = el_client.resolve_model(api_key or "", model_chain)
    if model_id != model_chain[0]:
        log("tts", f"model {model_chain[0]} unavailable on this tier; using {model_id}")

    log("tts", f"elevenlabs synth: voice={voice_name} model={model_id} "
               f"tagged={used_tagged} chars={len(text)}")
    result = el_client.synthesize_with_timestamps(
        text=text,
        voice_id=voice_id,
        model_id=model_id,
        api_key=api_key or "",
        output_format=el_cfg.get("output_format", el_client.DEFAULT_OUTPUT_FORMAT),
        stability=float(el_cfg.get("stability", 0.5)),
        similarity_boost=float(el_cfg.get("similarity_boost", 0.75)),
        style=float(el_cfg.get("style", 0.0)),
    )

    # Write audio first, then the debug dump, then the derived timings.
    paths.voice_mp3.write_bytes(result.audio_bytes)
    write_json(paths.root / "voice.el.raw.json", result.debug)

    alignment = result.alignment or result.normalized_alignment
    if not alignment or not alignment.get("characters"):
        raise el_client.ElevenLabsError(
            "ElevenLabs returned no character alignment; cannot build words.json"
        )
    align_source = "alignment" if result.alignment and result.alignment.get("characters") \
        else "normalized_alignment"
    words = el_align.words_from_alignment(alignment)
    if not words:
        raise el_client.ElevenLabsError("ElevenLabs alignment produced zero words")

    duration = audio_duration_seconds(paths.voice_mp3)
    write_json(paths.words_json, {
        "audio_duration": round(duration, 3),
        "source": "elevenlabs",
        "model_id": result.model_id,
        "voice_id": voice_id,
        "voice_name": voice_name,
        "tagged": used_tagged,
        "alignment_source": align_source,
        "char_count": result.char_count,
        "word_count": len(words),
        "words": words,
    })
    log("tts", f"wrote {paths.voice_mp3} ({paths.voice_mp3.stat().st_size} bytes, "
               f"{duration:.1f}s) + words.json ({len(words)} words, source=elevenlabs)")
    return paths.voice_mp3


# --------------------------------------------------------------------------- #
# edge-tts engine (default)
# --------------------------------------------------------------------------- #
async def _edge_stream(text: str, out_path: Path, voice: str, rate: str, pitch: str) -> list[dict]:
    """Save audio and return edge-tts word cues [{word,start,end}]."""
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text, voice=voice, rate=rate, pitch=pitch, boundary="WordBoundary"
    )
    cues: list[dict] = []
    with out_path.open("wb") as handle:
        async for chunk in communicate.stream():
            kind = chunk.get("type")
            if kind == "audio" and chunk.get("data"):
                handle.write(chunk["data"])
            elif kind == "WordBoundary":
                start = chunk["offset"] / TICKS_PER_SECOND
                end = (chunk["offset"] + chunk["duration"]) / TICKS_PER_SECOND
                cues.append({
                    "word": str(chunk.get("text", "")).strip(),
                    "start": round(start, 3),
                    "end": round(end, 3),
                })
    return cues


async def _synthesize_with_retry(
    text: str, out_path: Path, voice: str, rate: str, pitch: str
) -> list[dict]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(
                _edge_stream(text, out_path, voice, rate, pitch), timeout=SYNTH_TIMEOUT_S
            )
        except Exception as error:  # noqa: BLE001 - retry transient endpoint failures
            last_error = error
            log("tts", f"voice {voice} attempt {attempt}/{MAX_ATTEMPTS} failed ({error})")
            await asyncio.sleep(2 * attempt)
    raise RuntimeError(f"edge-tts exhausted retries for {voice}: {last_error}")


def _synthesize_edge(episode_dir: Path, config: dict, force: bool = False) -> Path:
    paths = EpisodePaths.for_dir(episode_dir).ensure_dirs()
    cues_path = paths.root / "voice.cues.json"
    if paths.voice_mp3.exists() and not force:
        log("tts", f"voice.mp3 exists, skipping ({paths.voice_mp3})")
        return paths.voice_mp3

    episode = read_json(paths.episode_json)
    narration = episode.get("narration", "").strip()
    if not narration:
        raise ValueError("episode.json has empty narration; run generate_script first")

    voice_cfg = config["voice"]
    voices = [voice_cfg["name"], voice_cfg.get("fallback_name", "en-US-GuyNeural")]
    rate = voice_cfg.get("rate", "+0%")
    pitch = voice_cfg.get("pitch", "+0Hz")

    last_error: Exception | None = None
    for voice in voices:
        try:
            cues = asyncio.run(
                _synthesize_with_retry(narration, paths.voice_mp3, voice, rate, pitch)
            )
            if paths.voice_mp3.exists() and paths.voice_mp3.stat().st_size > 0:
                write_json(cues_path, {"source": "edge-tts", "voice": voice, "words": cues})
                log("tts", f"wrote {paths.voice_mp3} (voice={voice}, "
                           f"{paths.voice_mp3.stat().st_size} bytes, {len(cues)} cues)")
                return paths.voice_mp3
        except Exception as error:  # noqa: BLE001 - try fallback voice next
            last_error = error
            log("tts", f"voice {voice} failed permanently ({error}); trying next")

    raise RuntimeError(f"edge-tts failed for all voices {voices}: {last_error}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthesize narration to voice.mp3")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--force", action="store_true", help="re-synthesize even if voice.mp3 exists")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    synthesize(Path(args.episode), load_config(), force=args.force)


if __name__ == "__main__":
    main()
