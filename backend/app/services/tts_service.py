"""TTS service — multi-provider text-to-speech with automatic fallback.

Provider cascade (configurable via TTS_PROVIDER_ORDER):
  1. ElevenLabs API  — fastest, highest quality, streaming support
  2. OpenAI TTS API  — high quality, reliable
  3. Edge-TTS        — free fallback, no API key needed

Character-budget awareness:
  ElevenLabs free tier = 10,000 chars/month per key.  The key manager tracks
  characters consumed and proactively switches to the next key before the limit
  is reached.  When ALL ElevenLabs keys are exhausted for the month, the cascade
  seamlessly falls through to the next provider (OpenAI → Edge-TTS) with zero
  audio disruption.

Features:
  • Character-budget tracking per ElevenLabs key (persisted across restarts)
  • API key rotation via APIKeyManager (handles rate-limits + quota exhaustion)
  • Parallel chunk processing (async semaphore-bounded)
  • Retry logic with exponential backoff per chunk
  • Sentence-aware text splitting (configurable chunk size)
  • Progress callback for real-time UI updates
"""

import io
import logging
import asyncio
from typing import Callable, Awaitable

import httpx
import edge_tts

from app.core.config import settings
from app.services.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

_TTS_CHUNK_TIMEOUT = 60          # seconds per TTS call
_TTS_MAX_RETRIES = 3             # retries per chunk
_MIN_VALID_MP3_BYTES = 256       # minimum bytes for a valid audio frame

# ── ElevenLabs free-tier limit ────────────────────────────────────────

_ELEVENLABS_MONTHLY_CHAR_LIMIT = int(
    settings.ELEVENLABS_MONTHLY_CHAR_LIMIT
    if hasattr(settings, "ELEVENLABS_MONTHLY_CHAR_LIMIT")
    else 10_000
)

# ── API Key Managers (initialised once at module load) ────────────────

_elevenlabs_keys = APIKeyManager(
    keys=settings.ELEVENLABS_API_KEYS,
    service_name="elevenlabs",
    char_limit_per_key=_ELEVENLABS_MONTHLY_CHAR_LIMIT,
    char_safety_margin=500,  # switch 500 chars before the limit
)
_openai_tts_keys = APIKeyManager(
    keys=settings.OPENAI_TTS_API_KEYS,
    service_name="openai-tts",
)

# Persistent HTTP client for TTS API calls (connection pooling)
_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    """Lazily create a persistent httpx client for TTS requests."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(_TTS_CHUNK_TIMEOUT, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


async def close_tts_client() -> None:
    """Close the persistent HTTP client. Call on app shutdown."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ══════════════════════════════════════════════════════════════════════
# TEXT SPLITTING
# ══════════════════════════════════════════════════════════════════════

def split_text_into_chunks(text: str, max_chars: int | None = None) -> list[str]:
    """Split long text into smaller chunks on sentence boundaries.

    Default chunk size comes from settings.TTS_CHUNK_SIZE (1500 chars).
    """
    max_chars = max_chars or settings.TTS_CHUNK_SIZE

    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""

    # Split into sentences
    sentences: list[str] = []
    temp = ""
    for char in text:
        temp += char
        if char in ".!?" and len(temp) > 1:
            sentences.append(temp.strip())
            temp = ""
    if temp.strip():
        sentences.append(temp.strip())

    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = current + " " + sentence if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks


# ══════════════════════════════════════════════════════════════════════
# PROVIDER: ELEVENLABS (with character-budget tracking)
# ══════════════════════════════════════════════════════════════════════

async def _elevenlabs_tts(text: str) -> bytes:
    """Generate speech via ElevenLabs API with character-budget awareness.

    Uses get_key_for_text() to pick a key that has enough remaining monthly
    budget.  After a successful call, records the characters consumed.
    When all keys are exhausted, raises RuntimeError so the cascade moves
    to the next provider seamlessly.
    """
    if not _elevenlabs_keys.has_keys:
        raise RuntimeError("No ElevenLabs API keys configured.")

    # Check if ALL keys have exhausted their monthly character budget
    if _elevenlabs_keys.all_keys_exhausted():
        remaining = _elevenlabs_keys.total_chars_remaining
        logger.warning(
            "[elevenlabs] All keys have exhausted their monthly character budget "
            "(%d chars remaining across all keys). Falling through to next provider.",
            remaining,
        )
        raise RuntimeError(
            f"All ElevenLabs keys exhausted for this month ({remaining} chars remaining). "
            "Falling through to next TTS provider."
        )

    # Pick a key with enough budget for this text
    key = _elevenlabs_keys.get_key_for_text(text)
    voice_id = settings.ELEVENLABS_VOICE_ID
    model_id = settings.ELEVENLABS_MODEL_ID

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    client = await _get_http_client()
    try:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            error_msg = response.text[:200]
            _elevenlabs_keys.report_failure(key, response.status_code, error_msg)
            raise RuntimeError(f"ElevenLabs API error {response.status_code}: {error_msg}")

        audio_bytes = response.content
        _elevenlabs_keys.report_success(key)

        # Record character usage — this triggers proactive key rotation
        # when the key approaches its monthly limit
        _elevenlabs_keys.report_chars_used(key, len(text))

        return audio_bytes

    except httpx.RequestError as exc:
        _elevenlabs_keys.report_failure(key, error_msg=str(exc))
        raise RuntimeError(f"ElevenLabs request error: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════
# PROVIDER: OPENAI TTS
# ══════════════════════════════════════════════════════════════════════

async def _openai_tts(text: str) -> bytes:
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
            error_msg = response.text[:200]
            _openai_tts_keys.report_failure(key, response.status_code, error_msg)
            raise RuntimeError(f"OpenAI TTS error {response.status_code}: {error_msg}")

        audio_bytes = response.content
        _openai_tts_keys.report_success(key)
        return audio_bytes

    except httpx.RequestError as exc:
        _openai_tts_keys.report_failure(key, error_msg=str(exc))
        raise RuntimeError(f"OpenAI TTS request error: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════
# PROVIDER: EDGE-TTS (free fallback)
# ══════════════════════════════════════════════════════════════════════

async def _edge_tts(text: str) -> bytes:
    """Generate speech via free Microsoft Edge TTS (no API key needed)."""
    communicate = edge_tts.Communicate(text, settings.EDGE_TTS_VOICE)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    result = buf.getvalue()
    if len(result) < _MIN_VALID_MP3_BYTES:
        raise ValueError(f"Edge-TTS returned empty audio ({len(result)} bytes)")
    return result


# ══════════════════════════════════════════════════════════════════════
# PROVIDER CASCADE (with retry + seamless fallback)
# ══════════════════════════════════════════════════════════════════════

# Map provider name → callable
_PROVIDERS: dict[str, Callable[[str], Awaitable[bytes]]] = {
    "elevenlabs": _elevenlabs_tts,
    "openai": _openai_tts,
    "edge": _edge_tts,
}


def _get_provider_order() -> list[tuple[str, Callable[[str], Awaitable[bytes]]]]:
    """Return the ordered list of available TTS providers.

    Skips providers with no keys (except edge which is free).
    Does NOT skip ElevenLabs even if all keys are budget-exhausted — the
    provider function itself handles that and raises RuntimeError, which
    the cascade catches and moves on.
    """
    order = []
    for name in settings.TTS_PROVIDER_ORDER:
        fn = _PROVIDERS.get(name)
        if fn is None:
            continue
        if name == "elevenlabs" and not _elevenlabs_keys.has_keys:
            continue
        if name == "openai" and not _openai_tts_keys.has_keys:
            continue
        order.append((name, fn))
    # Always include edge-tts as ultimate fallback
    if not any(n == "edge" for n, _ in order):
        order.append(("edge", _edge_tts))
    return order


async def text_to_mp3_bytes(text: str) -> bytes:
    """Convert text to MP3 using the configured provider cascade.

    Tries each provider in order. Within each provider, retries up to
    _TTS_MAX_RETRIES times with exponential backoff.

    When ElevenLabs keys run out of monthly characters, the cascade
    seamlessly falls through to the next provider — the audio output
    is uninterrupted.
    """
    providers = _get_provider_order()
    last_error: Exception | None = None

    for provider_name, provider_fn in providers:
        for attempt in range(1, _TTS_MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    provider_fn(text),
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
                # If all ElevenLabs keys are budget-exhausted, skip retries
                # and fall through to next provider immediately
                if "exhausted" in str(exc).lower() and provider_name == "elevenlabs":
                    logger.info(
                        "ElevenLabs monthly quota exhausted — seamlessly switching to next provider."
                    )
                    break
                logger.warning(
                    "%s TTS failed (attempt %s/%s): %s",
                    provider_name, attempt, _TTS_MAX_RETRIES, exc,
                )

            if attempt < _TTS_MAX_RETRIES:
                backoff = min(2 ** attempt, 8)
                await asyncio.sleep(backoff)

        logger.warning("All retries exhausted for %s, trying next provider...", provider_name)

    raise RuntimeError(
        f"All TTS providers failed after retries. Last error: {last_error}"
    )


# ══════════════════════════════════════════════════════════════════════
# PARALLEL CHUNK PROCESSING
# ══════════════════════════════════════════════════════════════════════

async def generate_chapter_audio(
    text: str,
    on_chunk_complete: Callable[[int, int], None] | None = None,
) -> bytes:
    """Generate audio for a full chapter by processing chunks in parallel.

    Parameters
    ----------
    text : str
        The full chapter text.
    on_chunk_complete : callable, optional
        Called with (completed_count, total_count) after each chunk finishes.

    Returns
    -------
    bytes
        Concatenated MP3 audio for the entire chapter.
    """
    chunks = split_text_into_chunks(text)
    total = len(chunks)

    if total == 0:
        raise ValueError("No text to convert to audio")

    if total == 1:
        audio = await text_to_mp3_bytes(chunks[0])
        if on_chunk_complete:
            on_chunk_complete(1, 1)
        return audio

    # Process chunks in parallel with bounded concurrency
    max_parallel = settings.TTS_PARALLEL_CHUNKS
    semaphore = asyncio.Semaphore(max_parallel)
    results: list[bytes | Exception] = [b""] * total
    completed_count = 0
    lock = asyncio.Lock()

    async def _process_chunk(index: int, chunk_text: str) -> None:
        nonlocal completed_count
        async with semaphore:
            try:
                audio = await text_to_mp3_bytes(chunk_text)
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
        asyncio.create_task(_process_chunk(i, chunk))
        for i, chunk in enumerate(chunks)
    ]

    errors: list[Exception] = []
    for task in asyncio.as_completed(tasks):
        try:
            await task
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise
        except Exception as exc:
            errors.append(exc)

    if errors:
        successful = [r for r in results if isinstance(r, bytes) and len(r) > 0]
        if not successful:
            raise RuntimeError(
                f"All {total} chunks failed. Last error: {errors[-1]}"
            )
        logger.warning(
            "%d/%d chunks failed during parallel generation. Continuing with %d successful.",
            len(errors), total, len(successful),
        )

    final_audio = b"".join(
        r for r in results if isinstance(r, bytes) and len(r) > 0
    )

    if len(final_audio) < _MIN_VALID_MP3_BYTES:
        raise ValueError("Final concatenated audio is too small — generation likely failed")

    return final_audio


# ══════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════

def get_audio_duration_seconds(audio_bytes: bytes) -> int:
    """Estimate duration of MP3 from byte size. ~16kBps for typical TTS output."""
    return max(1, len(audio_bytes) // 16000)


def get_active_provider() -> str:
    """Return the name of the provider that would be used for the next call."""
    providers = _get_provider_order()
    return providers[0][0] if providers else "none"


def get_tts_stats() -> dict:
    """Return usage statistics for all TTS key managers."""
    return {
        "active_provider": get_active_provider(),
        "elevenlabs": _elevenlabs_keys.get_stats() if _elevenlabs_keys.has_keys else [],
        "elevenlabs_total_chars_used": _elevenlabs_keys.total_chars_used,
        "elevenlabs_total_chars_remaining": _elevenlabs_keys.total_chars_remaining,
        "elevenlabs_all_exhausted": _elevenlabs_keys.all_keys_exhausted(),
        "openai_tts": _openai_tts_keys.get_stats() if _openai_tts_keys.has_keys else [],
        "provider_order": settings.TTS_PROVIDER_ORDER,
    }
