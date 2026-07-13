"""Thin ElevenLabs REST client for the tts stage.

Scope-safe: the project key is scoped (no user_read), so we never touch
/v1/user. Capabilities are probed only through the endpoints we actually need:
GET /v1/models (verify the model id) and POST .../with-timestamps (synthesis).

Quota exhaustion is surfaced as a dedicated ElevenLabsQuotaError so run.py can
recognise it and fall back to edge-tts instead of blocking the pipeline.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import requests

API_ROOT = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL_CHAIN = ["eleven_v3", "eleven_multilingual_v2"]
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
TIMEOUT_S = 180


class ElevenLabsError(RuntimeError):
    """Any ElevenLabs API failure."""


class ElevenLabsQuotaError(ElevenLabsError):
    """The key has no credits left. The fix lives outside the code:
    ElevenLabs dashboard -> API key -> credit quota."""


@dataclass(frozen=True)
class Synthesis:
    audio_bytes: bytes
    alignment: dict | None
    normalized_alignment: dict | None
    model_id: str
    voice_id: str
    char_count: int
    debug: dict  # raw response minus the audio blob, for voice.el.raw.json


def _headers(api_key: str) -> dict:
    return {"xi-api-key": api_key, "Content-Type": "application/json"}


def resolve_model(api_key: str, model_chain: list[str]) -> str:
    """First model from `model_chain` that this tier can use for TTS.

    Verifies exact ids via GET /v1/models. If the probe fails (network/scope),
    fall back to the first configured id and let synthesis report the real error.
    """
    try:
        response = requests.get(f"{API_ROOT}/models", headers=_headers(api_key), timeout=30)
    except requests.RequestException:
        return model_chain[0]
    if not response.ok:
        return model_chain[0]
    available = {
        m.get("model_id"): bool(m.get("can_do_text_to_speech"))
        for m in response.json()
    }
    for model_id in model_chain:
        if available.get(model_id):
            return model_id
    return model_chain[0]


def _raise_for_response(response: requests.Response) -> None:
    """Turn a non-2xx response into a typed, actionable error."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    detail = payload.get("detail")
    code = ""
    message = ""
    if isinstance(detail, dict):
        code = str(detail.get("code", ""))
        message = str(detail.get("message", ""))
    elif isinstance(detail, str):
        message = detail
    if code == "quota_exceeded" or "quota" in message.lower():
        raise ElevenLabsQuotaError(
            "ElevenLabs quota exhausted "
            f"(HTTP {response.status_code}): {message or response.text[:200]}. "
            "Fix: ElevenLabs dashboard -> API key -> credit quota (raise the cap "
            "above 0), then rerun with voice.engine=elevenlabs."
        )
    raise ElevenLabsError(
        f"ElevenLabs request failed (HTTP {response.status_code}, code={code or 'n/a'}): "
        f"{message or response.text[:300]}"
    )


def synthesize_with_timestamps(
    text: str,
    voice_id: str,
    model_id: str,
    api_key: str,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style: float = 0.0,
) -> Synthesis:
    """POST /v1/text-to-speech/{voice_id}/with-timestamps and decode the result."""
    if not api_key:
        raise ElevenLabsError(
            "ELEVENLABS_API_KEY is not set. Add it to pipeline/.env "
            "(loaded automatically by common.load_env)."
        )
    url = f"{API_ROOT}/text-to-speech/{voice_id}/with-timestamps"
    body = {
        "text": text,
        "model_id": model_id,
        "output_format": output_format,
        "voice_settings": {"stability": stability, "similarity_boost": similarity_boost, "style": style},
    }
    try:
        response = requests.post(url, headers=_headers(api_key), json=body, timeout=TIMEOUT_S)
    except requests.RequestException as error:
        raise ElevenLabsError(f"ElevenLabs request could not be sent: {error}") from error

    if not response.ok:
        _raise_for_response(response)

    data = response.json()
    audio_b64 = data.get("audio_base64")
    if not audio_b64:
        raise ElevenLabsError("ElevenLabs response missing audio_base64")
    try:
        audio_bytes = base64.b64decode(audio_b64)
    except (ValueError, TypeError) as error:
        raise ElevenLabsError(f"could not decode audio_base64: {error}") from error

    debug = {
        "model_id": model_id,
        "voice_id": voice_id,
        "output_format": output_format,
        "char_count": len(text),
        "audio_base64_bytes": len(audio_bytes),
        "alignment": data.get("alignment"),
        "normalized_alignment": data.get("normalized_alignment"),
    }
    return Synthesis(
        audio_bytes=audio_bytes,
        alignment=data.get("alignment"),
        normalized_alignment=data.get("normalized_alignment"),
        model_id=model_id,
        voice_id=voice_id,
        char_count=len(text),
        debug=debug,
    )
