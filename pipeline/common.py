"""Shared helpers for the Agent Shorts Kit renderer.

Every stage script imports from here so config handling and path resolution
stay identical whether a stage runs standalone or through run.py.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PIPELINE_DIR.parent
CONFIG_PATH = PIPELINE_DIR / "config.json"
ENV_PATH = PIPELINE_DIR / ".env"


def log(stage: str, message: str) -> None:
    """Single logging entry point (keeps raw print out of stage code)."""
    print(f"[{stage}] {message}", file=sys.stderr, flush=True)


def load_env(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE pairs from pipeline/.env into os.environ.

    Tiny manual parser so no extra dependency is pinned. Idempotent and
    non-destructive: a variable already present in the real environment wins,
    so `ELEVENLABS_API_KEY=... python run.py` still overrides the file. Blank
    lines, `#` comments and surrounding quotes are handled. Called once at
    import below, so every stage that imports common has env access.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable (populated from pipeline/.env at import)."""
    return os.environ.get(name, default)


# Populate os.environ from pipeline/.env as soon as any stage imports common.
load_env()


def audio_duration_seconds(audio_path: Path) -> float:
    """Measured duration of an audio/video file via ffprobe. Shared by the tts
    and align stages so both report the exact same number."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError(f"ffprobe could not read duration of {audio_path}") from error


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load config.json, the single source of truth. Fails loudly if missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"config.json not found at {path}. It is the single source of truth "
            "and must exist before any stage runs."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"config.json is not valid JSON: {error}") from error


@dataclass(frozen=True)
class EpisodePaths:
    """Immutable bundle of the file locations for one episode."""

    root: Path
    episode_json: Path
    voice_mp3: Path
    words_json: Path
    scenes_dir: Path
    out_dir: Path
    final_mp4: Path

    @staticmethod
    def for_dir(episode_dir: Path) -> "EpisodePaths":
        root = Path(episode_dir).resolve()
        return EpisodePaths(
            root=root,
            episode_json=root / "episode.json",
            voice_mp3=root / "voice.mp3",
            words_json=root / "words.json",
            scenes_dir=root / "scenes",
            out_dir=root / "out",
            final_mp4=root / "out" / "final.mp4",
        )

    def ensure_dirs(self) -> "EpisodePaths":
        self.root.mkdir(parents=True, exist_ok=True)
        self.scenes_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Expected JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_json_block(raw: str) -> dict:
    """Defensively parse JSON from an LLM response.

    Strips markdown fences and grabs the outermost {...} block so a stray
    prose line before/after the JSON does not break the pipeline.
    """
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in response: {raw[:200]!r}")
    return json.loads(text[start : end + 1])


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))
