"""Audio generation, streaming, and real-time event endpoints."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.database import db
from app.services.audio_generation import (
    generate_next_pending_chapter,
    get_audio_status_payload,
    get_enhanced_status,
    start_audio_generation,
)
from app.services.event_bus import event_bus
from app.services.tts_service import get_tts_stats, _elevenlabs_keys
from app.services.llm_chapter_service import get_llm_stats, _gemini_keys

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])


def require_admin():
    """Dependency that blocks generation when ADMIN_MODE is off."""
    if not settings.ADMIN_MODE:
        raise HTTPException(
            status_code=403,
            detail="Audio generation is only available for the developer. Admin mode is not enabled.",
        )
    return True


@router.post("/start/{book_id}", dependencies=[Depends(require_admin)])
async def start_generation(book_id: str, retry_failed: bool = False):
    """Start or resume background audio generation for a book."""
    try:
        return await start_audio_generation(book_id, retry_failed=retry_failed)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/generate-next/{book_id}", dependencies=[Depends(require_admin)])
async def generate_next_chapter(book_id: str):
    """Legacy endpoint for older clients that still generate one chapter at a time."""
    try:
        return await generate_next_pending_chapter(book_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/status/{book_id}")
async def audio_status(book_id: str):
    """Check the audio generation progress for a book."""
    try:
        return await get_audio_status_payload(book_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/enhanced-status/{book_id}")
async def enhanced_audio_status(book_id: str):
    """Enhanced status with pipeline state and API usage stats."""
    try:
        return await get_enhanced_status(book_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/events/{book_id}")
async def sse_events(book_id: str, request: Request):
    """Server-Sent Events stream for real-time generation progress.

    The client connects once and receives a continuous stream of events:
      - snapshot      : Full current state (sent immediately on connect)
      - step_change   : Pipeline step changed
      - chapter_start : A chapter started generating
      - chunk_progress: Sub-chapter chunk completed
      - chapter_done  : A chapter finished (ready or error)
      - api_usage     : Updated API usage stats
      - complete      : All chapters done
    """
    queue = event_bus.subscribe(book_id)

    async def event_generator():
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = event.get("type", "message")
                    data = json.dumps(event)
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive comment to prevent connection timeout
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(book_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/{book_id}/{chapter_number}")
async def stream_audio(book_id: str, chapter_number: int):
    """Get the audio URL for a specific chapter."""
    chapters = await db.select(
        "chapters",
        {
            "book_id": f"eq.{book_id}",
            "chapter_number": f"eq.{chapter_number}",
        },
    )
    if not chapters:
        raise HTTPException(status_code=404, detail="Chapter not found")

    chapter = chapters[0]
    if chapter["status"] != "ready" or not chapter.get("audio_storage_path"):
        raise HTTPException(status_code=404, detail="Audio not yet generated")

    audio_url = db.get_public_url("audiobooks", chapter["audio_storage_path"])
    return {"audio_url": audio_url, "duration_seconds": chapter["duration_seconds"]}


@router.get("/quota-check/{book_id}")
async def quota_check(book_id: str):
    """Pre-generation quota assessment.

    Calculates the total text size of all pending chapters in a book and
    compares it against the available ElevenLabs character budget and Gemini
    token budget.  Returns a structured assessment the frontend can display
    before the user clicks "Generate Audio".
    """
    # Fetch all chapters with their text content
    chapters = await db.select(
        "chapters",
        {
            "book_id": f"eq.{book_id}",
            "select": "id,chapter_number,title,status,text_content",
            "order": "chapter_number.asc",
        },
    )
    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found for this book.")

    # Calculate text metrics for pending chapters (ones that need audio)
    pending_chapters = [ch for ch in chapters if ch["status"] in ("pending", "error")]
    total_chars = sum(len((ch.get("text_content") or "").strip()) for ch in pending_chapters)
    total_all_chars = sum(len((ch.get("text_content") or "").strip()) for ch in chapters)
    pending_count = len(pending_chapters)
    total_count = len(chapters)
    already_ready = sum(1 for ch in chapters if ch["status"] == "ready")

    # ── ElevenLabs assessment ─────────────────────────────────────────
    el_configured = _elevenlabs_keys.has_keys
    el_key_count = len(_elevenlabs_keys.keys) if el_configured else 0
    el_limit_per_key = settings.ELEVENLABS_MONTHLY_CHAR_LIMIT
    el_total_budget = el_key_count * el_limit_per_key
    el_chars_used = _elevenlabs_keys.total_chars_used if el_configured else 0
    el_chars_remaining = _elevenlabs_keys.total_chars_remaining if el_configured else 0
    el_all_exhausted = _elevenlabs_keys.all_keys_exhausted() if el_configured else True

    # How much of this book can ElevenLabs cover?
    if el_configured and el_chars_remaining > 0:
        el_coverage_chars = min(total_chars, el_chars_remaining)
        el_coverage_pct = round((el_coverage_chars / total_chars * 100), 1) if total_chars > 0 else 100
        el_can_cover_full = el_chars_remaining >= total_chars
    else:
        el_coverage_chars = 0
        el_coverage_pct = 0
        el_can_cover_full = False

    # ── Gemini assessment (for chapter segmentation — already done at upload,
    #    but we report status for transparency) ────────────────────────
    gemini_configured = _gemini_keys.has_keys
    gemini_key_count = len(_gemini_keys.keys) if gemini_configured else 0
    # Gemini free tier: ~1M tokens/day ≈ ~4M chars/day
    # For chapter segmentation, we send the full book text once.
    # Approximate tokens = chars / 4
    gemini_est_tokens = total_all_chars // 4
    gemini_daily_limit = 1_000_000  # tokens (free tier for gemini-2.0-flash)
    gemini_can_segment = gemini_configured and gemini_est_tokens < gemini_daily_limit

    # ── Edge-TTS fallback assessment ──────────────────────────────────
    # Edge-TTS is always available, free, unlimited
    edge_available = True

    # ── Overall verdict ───────────────────────────────────────────────
    if total_chars == 0:
        verdict = "ready"
        verdict_message = "All chapters already have audio generated."
    elif el_can_cover_full:
        verdict = "ready"
        verdict_message = (
            f"Your ElevenLabs quota can fully cover this book. "
            f"{_fmt_chars(total_chars)} needed, {_fmt_chars(el_chars_remaining)} available "
            f"across {el_key_count} key(s)."
        )
    elif el_configured and el_chars_remaining > 0:
        # Partial ElevenLabs + Edge-TTS fallback
        el_portion = el_chars_remaining
        edge_portion = total_chars - el_portion
        verdict = "partial"
        verdict_message = (
            f"ElevenLabs will cover ~{_fmt_chars(el_portion)} "
            f"({el_coverage_pct}% of the book), then Edge-TTS (free) "
            f"will seamlessly handle the remaining ~{_fmt_chars(edge_portion)}. "
            f"No interruption — audio generation will be continuous."
        )
    elif el_all_exhausted and el_configured:
        verdict = "fallback"
        verdict_message = (
            f"All {el_key_count} ElevenLabs key(s) have used their monthly quota. "
            f"Audio will be generated entirely using Edge-TTS (free, unlimited). "
            f"Quality is still good — just a different voice."
        )
    else:
        verdict = "fallback"
        verdict_message = (
            "No ElevenLabs keys configured. Audio will be generated using "
            "Edge-TTS (free, unlimited, no API key needed)."
        )

    # Per-key breakdown
    el_key_breakdown = []
    if el_configured:
        for stat in _elevenlabs_keys.get_stats():
            el_key_breakdown.append({
                "key": stat["key_suffix"],
                "chars_used": stat["chars_used_this_month"],
                "chars_limit": stat["chars_limit"],
                "chars_remaining": stat["chars_remaining"],
                "active": stat["active"],
                "exhausted": stat["exhausted"],
            })

    return {
        "book_id": book_id,

        # Text metrics
        "total_chapters": total_count,
        "pending_chapters": pending_count,
        "already_ready": already_ready,
        "total_chars_needed": total_chars,
        "total_book_chars": total_all_chars,

        # ElevenLabs
        "elevenlabs": {
            "configured": el_configured,
            "key_count": el_key_count,
            "limit_per_key": el_limit_per_key,
            "total_budget": el_total_budget,
            "chars_used_this_month": el_chars_used,
            "chars_remaining": el_chars_remaining,
            "can_cover_full_book": el_can_cover_full,
            "coverage_percent": el_coverage_pct,
            "all_exhausted": el_all_exhausted,
            "keys": el_key_breakdown,
        },

        # Gemini (LLM for chapter segmentation)
        "gemini": {
            "configured": gemini_configured,
            "key_count": gemini_key_count,
            "estimated_tokens": gemini_est_tokens,
            "daily_token_limit": gemini_daily_limit,
            "can_segment": gemini_can_segment,
        },

        # Edge-TTS fallback
        "edge_tts": {
            "available": edge_available,
            "note": "Free, unlimited, no API key needed. Used as fallback when ElevenLabs quota runs out.",
        },

        # Overall
        "verdict": verdict,
        "verdict_message": verdict_message,
    }


def _fmt_chars(n: int) -> str:
    """Format character count as human-readable (e.g. '12.5k chars')."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M chars"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k chars"
    return f"{n:,} chars"


@router.get("/api-stats")
async def api_stats():
    """Diagnostic endpoint: show API key rotation stats for TTS and LLM providers."""
    return {
        "tts": get_tts_stats(),
        "llm": get_llm_stats(),
    }
