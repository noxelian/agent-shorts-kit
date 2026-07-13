"""Stage 4.5: synthesize the retro 8-bit SFX pack -> assets/sfx/*.wav.

Every cue is generated from scratch with numpy (no samples shipped): filtered
noise whooshes, a sine-thump impact, a rising riser, a square-wave blip and a
pitch-bending pop. All deterministic (fixed seed) and idempotent (existing WAVs
are left untouched unless --force), so re-running the pipeline never rewrites or
drifts the audio. Peaks are normalized to ~0.7; Remotion volume-scales them so
the whole layer sits under the untouched voice.

Standalone:  python sfx.py               (writes any missing WAVs)
             python sfx.py --force        (rewrite all)
Via run.py:  synthesize(config)
"""
from __future__ import annotations

import argparse
import wave
from pathlib import Path

from common import PROJECT_DIR, log

SAMPLE_RATE = 44_100
SEED = 20250704
PEAK = 0.7

# Every WAV the pack produces. run.py stages these into remotion/public/render.
SFX_NAMES = ("whoosh_up", "whoosh_down", "impact", "riser", "blip", "pop")
np = None


def _ensure_numpy():
    """Import numpy only when a WAV must actually be synthesized.

    Existing SFX files are reused for normal renders, so a stale/bad numpy wheel
    should not prevent publishing an otherwise ready Short.
    """
    global np
    if np is not None:
        return np
    try:
        import numpy as numpy_module
    except Exception as error:  # noqa: BLE001 - optional enhancement
        raise RuntimeError(f"numpy unavailable for SFX synthesis: {error}") from error
    np = numpy_module
    return np


def _t(seconds: float) -> np.ndarray:
    """Time base for a clip of the given length."""
    return np.linspace(0.0, seconds, int(SAMPLE_RATE * seconds), endpoint=False)


def _env(length: int, attack: float, decay: float) -> np.ndarray:
    """Linear attack + exponential-ish decay envelope over `length` samples."""
    attack_n = max(1, int(SAMPLE_RATE * attack))
    decay_n = max(1, int(SAMPLE_RATE * decay))
    rise = np.linspace(0.0, 1.0, min(attack_n, length))
    fall_n = max(1, length - rise.size)
    fall = np.exp(-np.linspace(0.0, 4.0, fall_n)) if decay_n > 0 else np.ones(fall_n)
    env = np.concatenate([rise, fall])
    return env[:length]


def _normalize(signal: np.ndarray) -> np.ndarray:
    """Scale so the absolute peak is PEAK; safe on a silent buffer."""
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak < 1e-9:
        return signal
    return signal * (PEAK / peak)


def _square(freq: np.ndarray) -> np.ndarray:
    """Square wave from an instantaneous-frequency array (phase = cumulative)."""
    phase = np.cumsum(2.0 * np.pi * freq / SAMPLE_RATE)
    return np.sign(np.sin(phase))


def _svf_bandpass_sweep(noise: np.ndarray, f_start: float, f_end: float, q: float) -> np.ndarray:
    """State-variable-filter bandpass whose centre frequency sweeps f_start->f_end.
    Gives filtered noise a clear directional 'whoosh' instead of flat hiss."""
    n = noise.size
    cutoff = np.linspace(f_start, f_end, n)
    low = 0.0
    band = 0.0
    out = np.empty(n)
    damp = 1.0 / max(0.01, q)
    for i in range(n):
        f = 2.0 * np.sin(np.pi * min(0.49, cutoff[i] / SAMPLE_RATE))
        low += f * band
        high = noise[i] - low - damp * band
        band += f * high
        out[i] = band
    return out


def _whoosh(rng: np.random.Generator, rising: bool) -> np.ndarray:
    seconds = 0.35
    noise = rng.standard_normal(int(SAMPLE_RATE * seconds))
    f_start, f_end = (600.0, 2600.0) if rising else (2600.0, 600.0)
    swept = _svf_bandpass_sweep(noise, f_start, f_end, q=1.4)
    env = _env(swept.size, attack=0.06, decay=0.29)
    return _normalize(swept * env)


def _impact() -> np.ndarray:
    seconds = 0.3
    t = _t(seconds)
    freq = np.linspace(60.0, 40.0, t.size)
    thump = np.sin(np.cumsum(2.0 * np.pi * freq / SAMPLE_RATE))
    body = thump * _env(t.size, attack=0.004, decay=0.29)
    click = np.zeros(t.size)
    click_n = int(SAMPLE_RATE * 0.006)
    rng = np.random.default_rng(SEED + 99)
    click[:click_n] = rng.standard_normal(click_n) * np.linspace(1.0, 0.0, click_n)
    return _normalize(body * 0.9 + click * 0.5)


def _riser() -> np.ndarray:
    seconds = 1.2
    t = _t(seconds)
    freq = np.linspace(90.0, 900.0, t.size)
    tone = _square(freq)
    rng = np.random.default_rng(SEED + 7)
    noise = rng.standard_normal(t.size)
    swell = np.linspace(0.0, 1.0, t.size) ** 2
    mix = tone * 0.4 + noise * 0.25
    return _normalize(mix * swell)


def _blip() -> np.ndarray:
    note = 0.06
    t = _t(note)
    lo = _square(np.full(t.size, 660.0)) * _env(t.size, attack=0.004, decay=0.05)
    hi = _square(np.full(t.size, 990.0)) * _env(t.size, attack=0.004, decay=0.05)
    return _normalize(np.concatenate([lo, hi]))


def _pop() -> np.ndarray:
    seconds = 0.15
    t = _t(seconds)
    freq = np.linspace(720.0, 300.0, t.size)
    tone = _square(freq)
    return _normalize(tone * _env(t.size, attack=0.004, decay=0.14))


def _render(name: str) -> np.ndarray:
    if name == "whoosh_up":
        return _whoosh(np.random.default_rng(SEED + 1), rising=True)
    if name == "whoosh_down":
        return _whoosh(np.random.default_rng(SEED + 2), rising=False)
    if name == "impact":
        return _impact()
    if name == "riser":
        return _riser()
    if name == "blip":
        return _blip()
    if name == "pop":
        return _pop()
    raise ValueError(f"unknown sfx name: {name}")


def _write_wav(path: Path, signal: np.ndarray) -> None:
    clipped = np.clip(signal, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())


def sfx_dir() -> Path:
    return PROJECT_DIR / "assets" / "sfx"


def synthesize(config: dict | None = None, force: bool = False) -> dict[str, Path]:
    """Ensure every SFX WAV exists in assets/sfx/. Returns name -> path."""
    del config  # accepted for a uniform stage signature; sfx has no config knobs
    out_dir = sfx_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = {name: out_dir / f"{name}.wav" for name in SFX_NAMES}
    if not force and all(path.exists() for path in expected.values()):
        for name in SFX_NAMES:
            log("sfx", f"{name}.wav exists, skipping")
        return expected
    _ensure_numpy()
    result: dict[str, Path] = {}
    for name in SFX_NAMES:
        path = out_dir / f"{name}.wav"
        if path.exists() and not force:
            log("sfx", f"{name}.wav exists, skipping")
        else:
            _write_wav(path, _render(name))
            log("sfx", f"{name}.wav synthesized")
        result[name] = path
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthesize the 8-bit SFX pack")
    parser.add_argument("--force", action="store_true", help="rewrite existing WAVs")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    paths = synthesize(force=args.force)
    print("\n".join(str(p) for p in paths.values()))


if __name__ == "__main__":
    main()
