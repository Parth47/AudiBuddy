"""TTS service with provider cascade and multilingual voice routing."""

from __future__ import annotations

import asyncio
import inspect
import io
import logging
import re
from typing import Awaitable, Callable

import edge_tts
import httpx

from app.core.config import settings
from app.services.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)

# Constants
_TTS_CHUNK_TIMEOUT = 60
_TTS_MAX_RETRIES = 3
_MIN_VALID_MP3_BYTES = 256
_SENTENCE_BOUNDARY_CHARS = ".!?।॥"
_DEVANAGARI_STORY_CHUNK_MIN = 2200

_ELEVENLABS_MONTHLY_CHAR_LIMIT = int(
    settings.ELEVENLABS_MONTHLY_CHAR_LIMIT
    if hasattr(settings, "ELEVENLABS_MONTHLY_CHAR_LIMIT")
    else 10_000
)

# API key managers
_elevenlabs_keys = APIKeyManager(
    keys=settings.ELEVENLABS_API_KEYS,
    service_name="elevenlabs",
    char_limit_per_key=_ELEVENLABS_MONTHLY_CHAR_LIMIT,
    char_safety_margin=500,
)
_openai_tts_keys = APIKeyManager(
    keys=settings.OPENAI_TTS_API_KEYS,
    service_name="openai-tts",
)

_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(_TTS_CHUNK_TIMEOUT, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


async def close_tts_client() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def _normalize_language(language: str | None) -> str:
    if not language:
        return "en"
    value = language.strip().lower()
    aliases = {
        "english": "en",
        "hindi": "hi",
        "marathi": "mr",
        "auto": "en",
    }
    return aliases.get(value, value if value in {"en", "hi", "mr", "mixed"} else "en")


def _is_devanagari_story_language(language: str | None) -> bool:
    return _normalize_language(language) in {"hi", "mr", "mixed"}


def _prepare_storytelling_text(text: str, language: str | None) -> str:
    """Lightweight text shaping to produce better narrative pacing."""
    normalized = re.sub(r"[ \t]+", " ", text).strip()
    if not normalized:
        return ""

    if _is_devanagari_story_language(language):
        # Encourage natural pauses for Hindi/Marathi narration.
        normalized = re.sub(r"\s*([।॥])\s*", r"\1\n", normalized)
        normalized = re.sub(r"\s*([!?])\s*", r"\1\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    return normalized


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Split very long sentences on whitespace if needed."""
    sentence = sentence.strip()
    if len(sentence) <= max_chars:
        return [sentence] if sentence else []

    words = sentence.split()
    if not words:
        return [sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars)]

    parts: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def split_text_into_chunks(
    text: str,
    max_chars: int | None = None,
    language: str | None = None,
) -> list[str]:
    """Split long text into chunks using sentence boundaries."""
    normalized_language = _normalize_language(language)
    max_chars = max_chars or settings.TTS_CHUNK_SIZE
    if _is_devanagari_story_language(normalized_language):
        max_chars = max(max_chars, _DEVANAGARI_STORY_CHUNK_MIN)

    prepared = _prepare_storytelling_text(text, normalized_language)
    if len(prepared) <= max_chars:
        return [prepared]

    normalized = re.sub(r"\s+", " ", prepared).strip()
    if not normalized:
        return [""]

    sentences = re.split(r"(?<=[.!?।॥])\s+", normalized)
    if len(sentences) == 1:
        sentences = _split_long_sentence(normalized, max_chars)
    else:
        expanded: list[str] = []
        for sentence in sentences:
            expanded.extend(_split_long_sentence(sentence, max_chars))
        sentences = expanded

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks or [normalized]


def _elevenlabs_voice_and_model(language: str) -> tuple[str, str]:
    """Pick ElevenLabs voice/model by language."""
    normalized = _normalize_language(language)
    if normalized == "hi":
        return settings.ELEVENLABS_VOICE_ID_HI, settings.ELEVENLABS_MULTILINGUAL_MODEL_ID
    if normalized == "mr":
        return settings.ELEVENLABS_VOICE_ID_MR, settings.ELEVENLABS_MULTILINGUAL_MODEL_ID
    if normalized == "mixed":
        return settings.ELEVENLABS_VOICE_ID_HI, settings.ELEVENLABS_MULTILINGUAL_MODEL_ID
    return settings.ELEVENLABS_VOICE_ID, settings.ELEVENLABS_MODEL_ID


def _edge_voice_for_language(language: str) -> str:
    normalized = _normalize_language(language)
    if normalized == "hi":
        return settings.EDGE_TTS_VOICE_HI
    if normalized == "mr":
        return settings.EDGE_TTS_VOICE_MR
    if normalized == "mixed":
        return settings.EDGE_TTS_VOICE_HI
    return settings.EDGE_TTS_VOICE


async def _elevenlabs_tts(text: str, language: str = "en") -> bytes:
    if not _elevenlabs_keys.has_keys:
        raise RuntimeError("No ElevenLabs API keys configured.")

    if _elevenlabs_keys.all_keys_exhausted():
        remaining = _elevenlabs_keys.total_chars_remaining
        raise RuntimeError(
            f"All ElevenLabs keys exhausted for this month ({remaining} chars remaining). "
            "Falling through to next TTS provider."
        )

    key = _elevenlabs_keys.get_key_for_text(text)
    voice_id, model_id = _elevenlabs_voice_and_model(language)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    normalized_language = _normalize_language(language)
    prepared_text = _prepare_storytelling_text(text, normalized_language)
    if not prepared_text:
        raise ValueError("No text to convert to audio after normalization.")

    is_devanagari_story = _is_devanagari_story_language(normalized_language)
    payload = {
        "text": prepared_text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.32 if is_devanagari_story else 0.45,
            "similarity_boost": 0.82 if is_devanagari_story else 0.75,
            "style": 0.40 if is_devanagari_story else 0.05,
            "use_speaker_boost": True,
        },
    }
    if normalized_language in {"hi", "mr"}:
        payload["language_code"] = normalized_language

    client = await _get_http_client()
    try:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            error_msg = response.text[:300]
            _elevenlabs_keys.report_failure(key, response.status_code, error_msg)
            raise RuntimeError(f"ElevenLabs API error {response.status_code}: {error_msg}")

        audio_bytes = response.content
        _elevenlabs_keys.report_success(key)
        _elevenlabs_keys.report_chars_used(key, len(prepared_text))
        return audio_bytes
    except httpx.RequestError as exc:
        _elevenlabs_keys.report_failure(key, error_msg=str(exc))
        raise RuntimeError(f"ElevenLabs request error: {exc}") from exc


async def _openai_tts(text: str, language: str = "en") -> bytes:
    """Generate speech via OpenAI TTS API."""
    if not _openai_tts_keys.has_keys:
        raise RuntimeError("No OpenAI TTS API keys configured.")

    key = _openai_tts_keys.get_key()
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENAI_TTS_MODEL,
        "input": text,
        "voice": settings.OPENAI_TTS_VOICE,
        "response_format": "mp3",
    }

    client = await _get_http_client()
    try:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            error_msg = response.text[:300]
            _openai_tts_keys.report_failure(key, response.status_code, error_msg)
            raise RuntimeError(f"OpenAI TTS error {response.status_code}: {error_msg}")

        audio_bytes = response.content
        _openai_tts_keys.report_success(key)
        return audio_bytes
    except httpx.RequestError as exc:
        _openai_tts_keys.report_failure(key, error_msg=str(exc))
        raise RuntimeError(f"OpenAI TTS request error: {exc}") from exc


async def _edge_tts(text: str, language: str = "en") -> bytes:
    """Generate speech via Microsoft Edge TTS (no API key required)."""
    voice = _edge_voice_for_language(language)
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])

    result = buf.getvalue()
    if len(result) < _MIN_VALID_MP3_BYTES:
        raise ValueError(f"Edge-TTS returned empty audio ({len(result)} bytes)")
    return result


ProviderFn = Callable[..., Awaitable[bytes]]

_PROVIDERS: dict[str, ProviderFn] = {
    "elevenlabs": _elevenlabs_tts,
    "openai": _openai_tts,
    "edge": _edge_tts,
}


def _get_provider_order() -> list[tuple[str, ProviderFn]]:
    order: list[tuple[str, ProviderFn]] = []
    for name in settings.TTS_PROVIDER_ORDER:
        fn = _PROVIDERS.get(name)
        if fn is None:
            continue
        if name == "elevenlabs" and not _elevenlabs_keys.has_keys:
            continue
        if name == "openai" and not _openai_tts_keys.has_keys:
            continue
        order.append((name, fn))

    if not any(name == "edge" for name, _ in order):
        order.append(("edge", _edge_tts))
    return order


async def _call_provider(provider_fn: ProviderFn, text: str, language: str) -> bytes:
    """Call providers with compatibility for legacy single-arg mocks/tests."""
    try:
        signature = inspect.signature(provider_fn)
    except (TypeError, ValueError):
        signature = None

    if signature and len(signature.parameters) < 2:
        return await provider_fn(text)  # type: ignore[misc]
    return await provider_fn(text, language)


async def text_to_mp3_bytes(text: str, language: str = "en") -> bytes:
    """Convert text to MP3 using configured provider cascade."""
    providers = _get_provider_order()
    normalized_language = _normalize_language(language)
    last_error: Exception | None = None

    for provider_name, provider_fn in providers:
        for attempt in range(1, _TTS_MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    _call_provider(provider_fn, text, normalized_language),
                    timeout=_TTS_CHUNK_TIMEOUT,
                )
                if len(result) < _MIN_VALID_MP3_BYTES:
                    raise ValueError(f"Audio too small ({len(result)} bytes)")
                return result
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"{provider_name} TTS timed out (attempt {attempt}/{_TTS_MAX_RETRIES})"
                )
                logger.warning("%s", last_error)
            except Exception as exc:
                last_error = exc
                if "exhausted" in str(exc).lower() and provider_name == "elevenlabs":
                    logger.info("ElevenLabs quota exhausted, moving to next provider.")
                    break
                logger.warning(
                    "%s TTS failed (attempt %s/%s): %s",
                    provider_name,
                    attempt,
                    _TTS_MAX_RETRIES,
                    exc,
                )

            if attempt < _TTS_MAX_RETRIES:
                await asyncio.sleep(min(2 ** attempt, 8))

        logger.warning("All retries exhausted for %s, trying next provider...", provider_name)

    raise RuntimeError(f"All TTS providers failed after retries. Last error: {last_error}")


async def generate_chapter_audio(
    text: str,
    on_chunk_complete: Callable[[int, int], None] | None = None,
    language: str = "en",
) -> bytes:
    """Generate chapter audio using chunked parallel TTS."""
    if not text or not text.strip():
        raise ValueError("No text to convert to audio")

    normalized_language = _normalize_language(language)
    chunks = split_text_into_chunks(text, language=normalized_language)
    total = len(chunks)

    if total == 0:
        raise ValueError("No text to convert to audio")

    if total == 1:
        if normalized_language == "en":
            audio = await text_to_mp3_bytes(chunks[0])
        else:
            audio = await text_to_mp3_bytes(chunks[0], normalized_language)
        if on_chunk_complete:
            on_chunk_complete(1, 1)
        return audio

    max_parallel = settings.TTS_PARALLEL_CHUNKS
    if _is_devanagari_story_language(normalized_language):
        # Sequential chunking keeps voice prosody more consistent for story narration.
        max_parallel = 1

    semaphore = asyncio.Semaphore(max_parallel)
    results: list[bytes | Exception] = [b""] * total
    completed_count = 0
    lock = asyncio.Lock()

    async def _process_chunk(index: int, chunk_text: str) -> None:
        nonlocal completed_count
        async with semaphore:
            try:
                if normalized_language == "en":
                    audio = await text_to_mp3_bytes(chunk_text)
                else:
                    audio = await text_to_mp3_bytes(chunk_text, normalized_language)
                results[index] = audio
            except Exception as exc:
                results[index] = exc
                raise
            finally:
                async with lock:
                    completed_count += 1
                    if on_chunk_complete:
                        on_chunk_complete(completed_count, total)

    tasks = [
        asyncio.create_task(_process_chunk(index, chunk))
        for index, chunk in enumerate(chunks)
    ]

    errors: list[Exception] = []
    for task in asyncio.as_completed(tasks):
        try:
            await task
        except asyncio.CancelledError:
            for item in tasks:
                item.cancel()
            raise
        except Exception as exc:
            errors.append(exc)

    if errors:
        successful = [r for r in results if isinstance(r, bytes) and r]
        if not successful:
            raise RuntimeError(f"All {total} chunks failed. Last error: {errors[-1]}")
        logger.warning(
            "%d/%d chunks failed during generation. Continuing with %d successful chunks.",
            len(errors),
            total,
            len(successful),
        )

    final_audio = b"".join(r for r in results if isinstance(r, bytes) and r)
    if len(final_audio) < _MIN_VALID_MP3_BYTES:
        raise ValueError("Final concatenated audio is too small. Generation likely failed.")
    return final_audio


def get_audio_duration_seconds(audio_bytes: bytes) -> int:
    """Estimate MP3 duration from byte size."""
    return max(1, len(audio_bytes) // 16000)


def get_active_provider() -> str:
    providers = _get_provider_order()
    return providers[0][0] if providers else "none"


def get_tts_stats() -> dict:
    return {
        "active_provider": get_active_provider(),
        "elevenlabs": _elevenlabs_keys.get_stats() if _elevenlabs_keys.has_keys else [],
        "elevenlabs_total_chars_used": _elevenlabs_keys.total_chars_used,
        "elevenlabs_total_chars_remaining": _elevenlabs_keys.total_chars_remaining,
        "elevenlabs_all_exhausted": _elevenlabs_keys.all_keys_exhausted(),
        "openai_tts": _openai_tts_keys.get_stats() if _openai_tts_keys.has_keys else [],
        "provider_order": settings.TTS_PROVIDER_ORDER,
    }


def add_tts_key(provider: str, api_key: str) -> bool:
    managers = {
        "elevenlabs": _elevenlabs_keys,
        "openai-tts": _openai_tts_keys,
    }
    manager = managers.get(provider)
    if manager is None:
        return False
    return manager.add_key(api_key)
