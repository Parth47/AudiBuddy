"""LLM-powered chapter segmentation — intelligently splits PDF text into chapters.

Uses an LLM to:
  1. Remove irrelevant sections (TOC, copyright, dedications, acknowledgements, etc.)
  2. Detect the actual start of meaningful book content
  3. Split text into logical chapters with clean boundaries

Provider cascade (configurable via LLM_PROVIDER_ORDER):
  1. Google Gemini  — FREE tier: 1M tokens/day for gemini-2.0-flash
  2. OpenAI (GPT-4o-mini — fast + cheap, if you have credits)
  3. Anthropic (Claude — if you have credits)

Token usage is tracked per-request and exposed via get_llm_usage() for
the live status dashboard.

Falls back to regex-based detection if all LLM providers fail.
"""

import json
import logging
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.services.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)

# ── Key Managers ──────────────────────────────────────────────────────

_gemini_keys = APIKeyManager(keys=settings.GOOGLE_GEMINI_API_KEYS, service_name="gemini")
_openai_keys = APIKeyManager(keys=settings.OPENAI_LLM_API_KEYS, service_name="openai-llm")
_anthropic_keys = APIKeyManager(keys=settings.ANTHROPIC_API_KEYS, service_name="anthropic")

# ── LLM timeout ──────────────────────────────────────────────────────

_LLM_TIMEOUT = 120  # seconds
_LLM_MAX_RETRIES = 2

# ── Persistent HTTP client ───────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(_LLM_TIMEOUT, connect=15.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def close_llm_client() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ── Token usage tracking ─────────────────────────────────────────────

@dataclass
class _LLMUsageTracker:
    """Tracks cumulative LLM token usage across all requests."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    last_provider: str = ""
    last_request_time: float = 0.0
    # Per-request history (last 20)
    history: list[dict] = field(default_factory=list)

    def record(self, provider: str, input_tokens: int, output_tokens: int, success: bool = True) -> None:
        self.total_requests += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.last_provider = provider
        self.last_request_time = time.time()
        if not success:
            self.failed_requests += 1
        entry = {
            "provider": provider,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "success": success,
            "time": self.last_request_time,
        }
        self.history.append(entry)
        if len(self.history) > 20:
            self.history = self.history[-20:]

    def to_dict(self) -> dict:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "last_provider": self.last_provider,
            "history": self.history[-5:],  # Last 5 for the dashboard
        }


_usage = _LLMUsageTracker()


def get_llm_usage() -> dict:
    """Return current LLM token usage stats (for the live dashboard)."""
    return _usage.to_dict()


# ── System prompt ────────────────────────────────────────────────────

_SEGMENTATION_PROMPT = """You are an expert book content analyst and audiobook producer. Your task is to process extracted PDF text and produce clean, well-structured chapters suitable for audiobook narration.

Instructions:
1. REMOVE all of the following sections (they are NOT actual book content):
   - Table of contents / Index
   - Copyright pages
   - Publisher information
   - Dedication pages
   - Acknowledgements
   - About the Author sections
   - Preface / Foreword (UNLESS they contain essential context for understanding the book)
   - Appendices and endnotes
   - Bibliography / References
   - Blank pages or page numbers
   - Any non-core content

2. DETECT the actual start of meaningful book content. This is usually after all the front-matter listed above.

3. Convert the remaining content into logically structured, context-aware, well-separated chapters:
   - Use explicit chapter headings if present ("Chapter 1", "Part One", numbered sections)
   - Otherwise detect semantic shifts in topic or narrative
   - Ensure chapters are suitable for audiobook narration and properly segmented for listening flow
   - Each chapter should be a self-contained listening segment

4. For each chapter, provide a clear title. If the original text has chapter titles, use them. If not, create descriptive titles based on the content.

5. Clean each chapter's text for narration:
   - Remove stray page numbers
   - Fix obvious OCR artifacts
   - Preserve paragraph breaks
   - Remove excessive whitespace
   - Remove any visual-only formatting (tables, charts descriptions) that don't work in audio

You MUST respond with ONLY valid JSON (no markdown fences, no explanation) in this exact format:
[
  {
    "chapter_title": "Chapter 1: The Surprising Power of Atomic Habits",
    "content": "The cleaned chapter text here..."
  }
]

If the text appears to have no clear chapter structure, split it into logical sections of roughly equal length and give each a descriptive title.

IMPORTANT: Respond with ONLY the JSON array. No other text."""


# ══════════════════════════════════════════════════════════════════════
# PROVIDER: GOOGLE GEMINI (FREE — 1M tokens/day)
# ══════════════════════════════════════════════════════════════════════

async def _gemini_segment(text: str) -> list[dict[str, str]]:
    """Use Google Gemini to segment chapter text. Tracks token usage."""
    if not _gemini_keys.has_keys:
        raise RuntimeError("No Google Gemini API keys configured.")

    key = _gemini_keys.get_key()
    model = settings.GOOGLE_GEMINI_MODEL

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    headers = {"Content-Type": "application/json"}

    # Gemini supports up to 1M tokens (~4M chars). Send entire text when possible.
    max_chars = 900_000
    truncated = text[:max_chars] if len(text) > max_chars else text

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{_SEGMENTATION_PROMPT}\n\nHere is the ENTIRE extracted PDF text to process. Process ALL of it:\n\n{truncated}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 32000,
            "responseMimeType": "application/json",
        },
    }

    client = await _get_http_client()
    try:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            error_msg = response.text[:300]
            _gemini_keys.report_failure(key, response.status_code, error_msg)
            _usage.record("gemini", len(truncated) // 4, 0, success=False)
            raise RuntimeError(f"Gemini API error {response.status_code}: {error_msg}")

        _gemini_keys.report_success(key)
        data = response.json()

        # Extract token usage from Gemini's usageMetadata
        usage_meta = data.get("usageMetadata", {})
        input_tokens = usage_meta.get("promptTokenCount", len(truncated) // 4)
        output_tokens = usage_meta.get("candidatesTokenCount", 0)
        _usage.record("gemini", input_tokens, output_tokens, success=True)

        logger.info(
            "[gemini] Token usage: %d input + %d output = %d total",
            input_tokens, output_tokens, input_tokens + output_tokens,
        )

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_llm_response(content)

    except httpx.RequestError as exc:
        _gemini_keys.report_failure(key, error_msg=str(exc))
        _usage.record("gemini", len(truncated) // 4, 0, success=False)
        raise RuntimeError(f"Gemini request error: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════
# PROVIDER: OPENAI
# ══════════════════════════════════════════════════════════════════════

async def _openai_segment(text: str) -> list[dict[str, str]]:
    if not _openai_keys.has_keys:
        raise RuntimeError("No OpenAI LLM API keys configured.")

    key = _openai_keys.get_key()
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    max_chars = 300_000
    truncated = text[:max_chars] if len(text) > max_chars else text

    payload = {
        "model": settings.OPENAI_LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SEGMENTATION_PROMPT},
            {"role": "user", "content": f"Here is the extracted PDF text to process:\n\n{truncated}"},
        ],
        "temperature": 0.1,
        "max_tokens": 16000,
        "response_format": {"type": "json_object"},
    }

    client = await _get_http_client()
    try:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            error_msg = response.text[:300]
            _openai_keys.report_failure(key, response.status_code, error_msg)
            _usage.record("openai", len(truncated) // 4, 0, success=False)
            raise RuntimeError(f"OpenAI LLM error {response.status_code}: {error_msg}")

        _openai_keys.report_success(key)
        data = response.json()

        # Extract token usage from OpenAI response
        oai_usage = data.get("usage", {})
        input_tokens = oai_usage.get("prompt_tokens", len(truncated) // 4)
        output_tokens = oai_usage.get("completion_tokens", 0)
        _usage.record("openai", input_tokens, output_tokens, success=True)

        content = data["choices"][0]["message"]["content"]
        return _parse_llm_response(content)

    except httpx.RequestError as exc:
        _openai_keys.report_failure(key, error_msg=str(exc))
        _usage.record("openai", len(truncated) // 4, 0, success=False)
        raise RuntimeError(f"OpenAI LLM request error: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════
# PROVIDER: ANTHROPIC
# ══════════════════════════════════════════════════════════════════════

async def _anthropic_segment(text: str) -> list[dict[str, str]]:
    if not _anthropic_keys.has_keys:
        raise RuntimeError("No Anthropic API keys configured.")

    key = _anthropic_keys.get_key()
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": key,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }

    max_chars = 400_000
    truncated = text[:max_chars] if len(text) > max_chars else text

    payload = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": 16000,
        "temperature": 0.1,
        "system": _SEGMENTATION_PROMPT,
        "messages": [{"role": "user", "content": f"Here is the extracted PDF text to process:\n\n{truncated}"}],
    }

    client = await _get_http_client()
    try:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            error_msg = response.text[:300]
            _anthropic_keys.report_failure(key, response.status_code, error_msg)
            _usage.record("anthropic", len(truncated) // 4, 0, success=False)
            raise RuntimeError(f"Anthropic LLM error {response.status_code}: {error_msg}")

        _anthropic_keys.report_success(key)
        data = response.json()

        # Extract token usage from Anthropic response
        anth_usage = data.get("usage", {})
        input_tokens = anth_usage.get("input_tokens", len(truncated) // 4)
        output_tokens = anth_usage.get("output_tokens", 0)
        _usage.record("anthropic", input_tokens, output_tokens, success=True)

        content = data["content"][0]["text"]
        return _parse_llm_response(content)

    except httpx.RequestError as exc:
        _anthropic_keys.report_failure(key, error_msg=str(exc))
        _usage.record("anthropic", len(truncated) // 4, 0, success=False)
        raise RuntimeError(f"Anthropic LLM request error: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════
# RESPONSE PARSING
# ══════════════════════════════════════════════════════════════════════

def _parse_llm_response(content: str) -> list[dict[str, str]]:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("LLM returned invalid JSON: %s...", content[:200])
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    chapters: list[dict[str, Any]]
    if isinstance(parsed, list):
        chapters = parsed
    elif isinstance(parsed, dict):
        for key in ("chapters", "data", "result", "results"):
            if key in parsed and isinstance(parsed[key], list):
                chapters = parsed[key]
                break
        else:
            raise ValueError(f"LLM returned unexpected JSON structure: {list(parsed.keys())}")
    else:
        raise ValueError(f"LLM returned unexpected type: {type(parsed)}")

    result: list[dict[str, str]] = []
    for i, ch in enumerate(chapters):
        title = ch.get("chapter_title") or ch.get("title") or f"Chapter {i + 1}"
        text = ch.get("content") or ch.get("text") or ch.get("text_content") or ""
        text = text.strip()
        if text:
            result.append({"title": str(title), "text": text})

    if not result:
        raise ValueError("LLM returned no chapters with content")

    return result


# ══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

_PROVIDERS: dict[str, Any] = {
    "gemini": _gemini_segment,
    "openai": _openai_segment,
    "anthropic": _anthropic_segment,
}


async def segment_chapters_with_llm(text: str) -> list[dict[str, str]] | None:
    """Segment text into chapters using LLM, with provider fallback.
    Returns None if all providers fail (caller should use regex fallback).
    """
    providers = []
    for name in settings.LLM_PROVIDER_ORDER:
        fn = _PROVIDERS.get(name)
        if fn is None:
            continue
        if name == "gemini" and not _gemini_keys.has_keys:
            continue
        if name == "openai" and not _openai_keys.has_keys:
            continue
        if name == "anthropic" and not _anthropic_keys.has_keys:
            continue
        providers.append((name, fn))

    if not providers:
        logger.warning("No LLM providers configured. Falling back to regex.")
        return None

    last_error: Exception | None = None
    for provider_name, provider_fn in providers:
        for attempt in range(1, _LLM_MAX_RETRIES + 1):
            try:
                logger.info("Chapter segmentation via %s (attempt %s/%s)...", provider_name, attempt, _LLM_MAX_RETRIES)
                result = await asyncio.wait_for(provider_fn(text), timeout=_LLM_TIMEOUT)
                if result and len(result) > 0:
                    logger.info("LLM segmentation via %s: %d chapters.", provider_name, len(result))
                    return result
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                last_error = TimeoutError(f"{provider_name} LLM timed out")
                logger.warning("%s", last_error)
            except Exception as exc:
                last_error = exc
                logger.warning("%s LLM failed (attempt %s/%s): %s", provider_name, attempt, _LLM_MAX_RETRIES, exc)
            if attempt < _LLM_MAX_RETRIES:
                await asyncio.sleep(2)
        logger.warning("All retries exhausted for %s LLM.", provider_name)

    logger.error("All LLM providers failed. Last error: %s", last_error)
    return None


def get_llm_stats() -> dict:
    """Key rotation stats (for api-stats endpoint)."""
    return {
        "gemini": _gemini_keys.get_stats() if _gemini_keys.has_keys else [],
        "openai": _openai_keys.get_stats() if _openai_keys.has_keys else [],
        "anthropic": _anthropic_keys.get_stats() if _anthropic_keys.has_keys else [],
        "provider_order": settings.LLM_PROVIDER_ORDER,
        "usage": _usage.to_dict(),
    }
