"""Translation service using ElevenLabs dubbing workflow.

There is no stable public text-to-text translation endpoint in ElevenLabs API docs.
To keep integration official, this service translates text by:
1) generating source-language speech with ElevenLabs TTS
2) dubbing that audio into target language
3) fetching translated transcript JSON
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.api_key_manager import APIKeyManager
from app.services.pdf_service import normalize_language_code, normalize_unicode_text

logger = logging.getLogger(__name__)

_TRANSLATABLE_LANGS = {"en", "hi", "mr"}
_AUTO_MARKERS = {"", "auto", "automatic"}
_NONE_MARKERS = {"none", "off", "original", "source"}
_TTS_ENDPOINT_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
_DUBBING_ENDPOINT = "https://api.elevenlabs.io/v1/dubbing"
_TRANSCRIPT_ENDPOINT_FMT = "https://api.elevenlabs.io/v1/dubbing/{dubbing_id}/transcript/{language_code}"
_MIN_VALID_AUDIO_BYTES = 256

_translation_keys = APIKeyManager(
    keys=settings.ELEVENLABS_API_KEYS,
    service_name="elevenlabs-translation",
)

_http_client: httpx.AsyncClient | None = None


@dataclass
class TranslationResult:
    text: str
    applied: bool
    source_language: str
    tts_language: str
    target_language: str | None = None


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        timeout = max(30, int(settings.ELEVENLABS_TRANSLATION_TIMEOUT_SECONDS))
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def close_translation_client() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def normalize_translation_target(target: str | None) -> str:
    if target is None:
        return "auto"
    value = target.strip().lower()
    aliases = {
        "english": "en",
        "hindi": "hi",
        "marathi": "mr",
    }
    value = aliases.get(value, value)
    if value in _AUTO_MARKERS:
        return "auto"
    if value in _NONE_MARKERS:
        return "none"
    if value in _TRANSLATABLE_LANGS:
        return value
    return "auto"


def resolve_translation_target(source_language: str, requested_target: str | None) -> str | None:
    """Resolve final target language or return None when translation is not needed."""
    source = normalize_language_code(source_language)
    target = normalize_translation_target(requested_target)

    if target == "none":
        return None

    if target == "auto":
        default_target = normalize_translation_target(settings.ELEVENLABS_TRANSLATION_DEFAULT_TARGET)
        if source in set(settings.ELEVENLABS_TRANSLATION_SOURCE_LANGS):
            return default_target if default_target in _TRANSLATABLE_LANGS else "en"
        return None

    if target == source:
        return None
    return target if target in _TRANSLATABLE_LANGS else None


def _tts_voice_and_model(language: str) -> tuple[str, str]:
    normalized = normalize_language_code(language)
    if normalized == "hi":
        return settings.ELEVENLABS_VOICE_ID_HI, settings.ELEVENLABS_MULTILINGUAL_MODEL_ID
    if normalized == "mr":
        return settings.ELEVENLABS_VOICE_ID_MR, settings.ELEVENLABS_MULTILINGUAL_MODEL_ID
    return settings.ELEVENLABS_VOICE_ID, settings.ELEVENLABS_MODEL_ID


def _split_text_for_translation(text: str, max_chars: int) -> list[str]:
    normalized = re.sub(r"\s+", " ", normalize_unicode_text(text)).strip()
    if not normalized:
        return [""]
    if len(normalized) <= max_chars:
        return [normalized]

    sentences = re.split(r"(?<=[.!?।॥])\s+", normalized)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)

    if not chunks:
        return [normalized[i:i + max_chars] for i in range(0, len(normalized), max_chars)]
    return chunks


def _merge_transcript_utterances(payload: dict) -> str:
    utterances = payload.get("utterances")
    if not isinstance(utterances, list):
        return ""
    parts = [str(item.get("text", "")).strip() for item in utterances if isinstance(item, dict)]
    text = " ".join(part for part in parts if part)
    text = normalize_unicode_text(text)
    text = re.sub(r"\s+([,.!?;:।॥])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


async def _synthesize_source_audio(text: str, source_language: str, api_key: str) -> bytes:
    voice_id, model_id = _tts_voice_and_model(source_language)
    url = f"{_TTS_ENDPOINT_BASE}/{voice_id}/stream"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload: dict = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "use_speaker_boost": True,
        },
    }
    if source_language in {"en", "hi", "mr"}:
        payload["language_code"] = source_language

    client = await _get_http_client()
    response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"TTS-for-translation failed ({response.status_code}): {response.text[:300]}")

    audio = response.content
    if len(audio) < _MIN_VALID_AUDIO_BYTES:
        raise RuntimeError(f"TTS-for-translation returned too little audio ({len(audio)} bytes).")
    return audio


async def _create_dub(audio_bytes: bytes, source_language: str, target_language: str, api_key: str) -> str:
    headers = {"xi-api-key": api_key}
    data = {
        "source_lang": source_language,
        "target_lang": target_language,
    }
    files = {
        "file": ("translation-source.mp3", audio_bytes, "audio/mpeg"),
    }

    client = await _get_http_client()
    response = await client.post(_DUBBING_ENDPOINT, data=data, files=files, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"Dubbing create failed ({response.status_code}): {response.text[:300]}")

    payload = response.json()
    dubbing_id = str(payload.get("dubbing_id", "")).strip()
    if not dubbing_id:
        raise RuntimeError("Dubbing create response did not include dubbing_id.")
    return dubbing_id


async def _wait_until_dubbed(dubbing_id: str, api_key: str) -> None:
    timeout_seconds = max(30, int(settings.ELEVENLABS_TRANSLATION_TIMEOUT_SECONDS))
    poll_interval = max(0.5, float(settings.ELEVENLABS_TRANSLATION_POLL_INTERVAL_SECONDS))
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    client = await _get_http_client()
    headers = {"xi-api-key": api_key}
    url = f"{_DUBBING_ENDPOINT}/{dubbing_id}"

    while True:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Dubbing status failed ({response.status_code}): {response.text[:300]}")

        payload = response.json()
        status = str(payload.get("status", "")).strip().lower()
        if status in {"dubbed", "completed", "done", "ready"}:
            return
        if status in {"failed", "error", "cancelled"}:
            error = str(payload.get("error", "")).strip()
            raise RuntimeError(f"Dubbing failed with status '{status}'. {error}".strip())

        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"Dubbing timed out after {timeout_seconds} seconds.")
        await asyncio.sleep(poll_interval)


async def _get_dubbed_transcript(dubbing_id: str, target_language: str, api_key: str) -> str:
    client = await _get_http_client()
    headers = {"xi-api-key": api_key}
    url = _TRANSCRIPT_ENDPOINT_FMT.format(
        dubbing_id=dubbing_id,
        language_code=target_language,
    )
    response = await client.get(url, headers=headers, params={"format_type": "json"})
    if response.status_code != 200:
        raise RuntimeError(f"Dubbing transcript failed ({response.status_code}): {response.text[:300]}")

    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("Dubbing transcript response was not valid JSON.") from exc

    text = _merge_transcript_utterances(payload if isinstance(payload, dict) else {})
    if not text:
        raise RuntimeError("Translated transcript was empty.")
    return text


async def _delete_dub(dubbing_id: str, api_key: str) -> None:
    if not settings.ELEVENLABS_TRANSLATION_DELETE_DUB:
        return
    try:
        client = await _get_http_client()
        headers = {"xi-api-key": api_key}
        await client.delete(f"{_DUBBING_ENDPOINT}/{dubbing_id}", headers=headers)
    except Exception:
        logger.debug("Failed to delete dubbing job %s", dubbing_id)


async def _translate_chunk(chunk: str, source_language: str, target_language: str) -> str:
    retries = max(1, int(settings.ELEVENLABS_TRANSLATION_RETRIES))
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        key = ""
        dubbing_id = ""
        try:
            key = _translation_keys.get_key()
            audio = await _synthesize_source_audio(chunk, source_language, key)
            dubbing_id = await _create_dub(audio, source_language, target_language, key)
            await _wait_until_dubbed(dubbing_id, key)
            translated = await _get_dubbed_transcript(dubbing_id, target_language, key)
            _translation_keys.report_success(key)
            return translated
        except Exception as exc:
            last_error = exc
            status_code = None
            if isinstance(exc, httpx.HTTPStatusError):
                status_code = exc.response.status_code
            if key:
                _translation_keys.report_failure(key, status_code=status_code, error_msg=str(exc))
            logger.warning(
                "Translation chunk failed (attempt %d/%d): %s",
                attempt,
                retries,
                exc,
            )
            if attempt < retries:
                await asyncio.sleep(min(2 ** attempt, 6))
        finally:
            if dubbing_id and key:
                await _delete_dub(dubbing_id, key)

    raise RuntimeError(f"Translation failed after {retries} attempts. Last error: {last_error}")


async def translate_text_via_elevenlabs(text: str, source_language: str, target_language: str) -> str:
    max_chars = max(300, int(settings.ELEVENLABS_TRANSLATION_MAX_CHARS))
    chunks = _split_text_for_translation(text, max_chars=max_chars)
    translated_chunks: list[str] = []

    for chunk in chunks:
        if not chunk.strip():
            continue
        translated_chunks.append(await _translate_chunk(chunk, source_language, target_language))

    merged = " ".join(part.strip() for part in translated_chunks if part.strip())
    merged = normalize_unicode_text(merged)
    merged = re.sub(r"\s+([,.!?;:।॥])", r"\1", merged)
    return re.sub(r"\s+", " ", merged).strip()


async def maybe_translate_for_tts(
    text: str,
    source_language: str,
    requested_target: str | None = "auto",
) -> TranslationResult:
    source = normalize_language_code(source_language)
    source_for_tts = source if source in {"en", "hi", "mr", "mixed"} else "en"
    target = resolve_translation_target(source, requested_target)

    if not text.strip() or not target:
        return TranslationResult(
            text=text,
            applied=False,
            source_language=source_for_tts,
            tts_language=source_for_tts,
            target_language=None,
        )

    if not settings.ELEVENLABS_TRANSLATION_ENABLED:
        return TranslationResult(
            text=text,
            applied=False,
            source_language=source_for_tts,
            tts_language=source_for_tts,
            target_language=None,
        )

    if not _translation_keys.has_keys:
        logger.warning("Translation requested but ELEVENLABS_API_KEYS is not configured. Using source text.")
        return TranslationResult(
            text=text,
            applied=False,
            source_language=source_for_tts,
            tts_language=source_for_tts,
            target_language=None,
        )

    source_for_translation = "hi" if source == "mixed" else source_for_tts

    try:
        translated = await translate_text_via_elevenlabs(text, source_for_translation, target)
        if not translated.strip():
            raise RuntimeError("Translated text was empty.")
        return TranslationResult(
            text=translated,
            applied=True,
            source_language=source_for_tts,
            tts_language=target,
            target_language=target,
        )
    except Exception as exc:
        logger.warning(
            "Translation failed for source=%s target=%s. %s",
            source_for_translation,
            target,
            exc,
        )
        if settings.ELEVENLABS_TRANSLATION_FALLBACK_TO_SOURCE:
            return TranslationResult(
                text=text,
                applied=False,
                source_language=source_for_tts,
                tts_language=source_for_tts,
                target_language=None,
            )
        raise
