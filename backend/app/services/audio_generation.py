"""Background audio generation orchestration.

Production-hardened: parallel TTS via generate_chapter_audio(), proper error
recovery, cancellation handling, granular progress tracking, SSE event bus
integration, and no silent failures.
"""

import asyncio
import logging
import time
from collections.abc import Iterable

from app.core.database import db
from app.services.tts_service import generate_chapter_audio, get_audio_duration_seconds, get_tts_stats
from app.services.event_bus import event_bus, STEP_GENERATING
from app.services.llm_chapter_service import get_llm_stats
from app.services.translation_service import maybe_translate_for_tts

logger = logging.getLogger(__name__)

STATUS_SELECT = ",".join(
    [
        "id",
        "book_id",
        "chapter_number",
        "title",
        "status",
        "duration_seconds",
        "audio_storage_path",
        "created_at",
    ]
)

DETAIL_SELECT = f"{STATUS_SELECT},text_content"

# ── In-memory job tracking ────────────────────────────────────────────

_active_jobs: set[str] = set()
_active_tasks: dict[str, asyncio.Task[None]] = {}
_active_chapter_progress: dict[str, dict] = {}


def _is_job_running(book_id: str) -> bool:
    task = _active_tasks.get(book_id)
    return book_id in _active_jobs or (task is not None and not task.done())


def _processed_count(chapters: Iterable[dict]) -> int:
    return sum(1 for chapter in chapters if chapter["status"] in {"ready", "error"})


# ══════════════════════════════════════════════════════════════════════
# STATUS REPORTING
# ══════════════════════════════════════════════════════════════════════

async def get_audio_status_payload(book_id: str) -> dict:
    """Return a frontend-friendly snapshot of audio generation state."""
    chapters = await db.select(
        "chapters",
        {
            "book_id": f"eq.{book_id}",
            "select": STATUS_SELECT,
            "order": "chapter_number.asc",
        },
    )
    if not chapters:
        raise LookupError("No chapters found")

    total = len(chapters)
    ready = sum(1 for chapter in chapters if chapter["status"] == "ready")
    generating = sum(1 for chapter in chapters if chapter["status"] == "generating")
    error_count = sum(1 for chapter in chapters if chapter["status"] == "error")
    processed = _processed_count(chapters)
    pending = max(total - processed - generating, 0)
    completed = pending == 0 and generating == 0

    # Calculate progress percentage with sub-chapter chunk granularity
    progress_percent = int((processed / total) * 100) if total > 0 else 0
    if book_id in _active_chapter_progress and total > 0:
        prog = _active_chapter_progress[book_id]
        if prog["total_chunks"] > 0:
            chunk_ratio = prog["completed_chunks"] / prog["total_chunks"]
            # Add fractional progress for the currently-generating chapter
            progress_percent += int((1 / total) * chunk_ratio * 100)
            progress_percent = min(100, progress_percent)

    return {
        "book_id": book_id,
        "total_chapters": total,
        "ready": ready,
        "generating": generating,
        "pending": pending,
        "error": error_count,
        "processed": processed,
        "completed": completed,
        "is_running": _is_job_running(book_id) or generating > 0,
        "can_start": pending > 0,
        "can_retry_failed": error_count > 0,
        "total_duration_seconds": sum(
            chapter.get("duration_seconds", 0)
            for chapter in chapters
            if chapter["status"] == "ready"
        ),
        "progress_percent": progress_percent,
        "chapters": chapters,
    }


# ══════════════════════════════════════════════════════════════════════
# START / CANCEL / LEGACY ENTRY POINTS
# ══════════════════════════════════════════════════════════════════════

async def start_audio_generation(book_id: str, retry_failed: bool = False) -> dict:
    """Start background generation for a book if work remains.

    HARD RULE: Audio generation MUST NEVER proceed unless the book has been
    through the chapter processing pipeline (status = 'ready') and chapters
    exist in the database with text_content populated.
    """
    # ── Pipeline gate: verify book has been through chapter processing ──
    books = await db.select("books", {"id": f"eq.{book_id}", "select": "id,status,total_chapters"})
    if not books:
        raise LookupError(f"Book {book_id} not found")

    book = books[0]
    if book["status"] not in ("ready",):
        raise ValueError(
            f"Audio generation blocked: book status is '{book['status']}'. "
            "Chapters must be processed first (book status must be 'ready')."
        )
    if (book.get("total_chapters") or 0) == 0:
        raise ValueError(
            "Audio generation blocked: book has 0 chapters. "
            "PDF must be processed into chapters before audio can be generated."
        )

    current = await get_audio_status_payload(book_id)

    if _is_job_running(book_id):
        return {
            "started": False,
            "message": "Audio generation is already running.",
            "status": current,
        }

    # Reset failed chapters to pending if retry requested
    if retry_failed and current["error"] > 0:
        failed = await db.select(
            "chapters",
            {
                "book_id": f"eq.{book_id}",
                "status": "eq.error",
                "select": "id",
            },
        )
        for chapter in failed:
            await db.update(
                "chapters",
                {"status": "pending", "duration_seconds": 0, "audio_storage_path": None},
                {"id": chapter["id"]},
            )

    # Reset any stale "generating" chapters back to pending
    stale = await db.select(
        "chapters",
        {
            "book_id": f"eq.{book_id}",
            "status": "eq.generating",
            "select": "id",
        },
    )
    for chapter in stale:
        await db.update("chapters", {"status": "pending"}, {"id": chapter["id"]})

    refreshed = await get_audio_status_payload(book_id)
    if refreshed["pending"] == 0:
        message = (
            "All chapters already have audio."
            if refreshed["error"] == 0
            else "Generation is complete, but some chapters failed. Retry failed chapters to try again."
        )
        return {"started": False, "message": message, "status": refreshed}

    _active_jobs.add(book_id)
    task = asyncio.create_task(_run_generation_task(book_id))
    _active_tasks[book_id] = task

    started_status = await get_audio_status_payload(book_id)
    started_status["is_running"] = True
    return {
        "started": True,
        "message": "Audio generation started.",
        "status": started_status,
    }


async def cancel_audio_generation(book_id: str) -> bool:
    """Cancel an in-flight generation task for a book if one exists."""
    task = _active_tasks.get(book_id)
    if task is None or task.done():
        _active_jobs.discard(book_id)
        _active_tasks.pop(book_id, None)
        return False

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("Audio generation cancelled for book %s", book_id)
    finally:
        _active_jobs.discard(book_id)
        _active_tasks.pop(book_id, None)
        _active_chapter_progress.pop(book_id, None)

        # Reset any chapters stuck in "generating" back to "pending"
        stale = await db.select(
            "chapters",
            {
                "book_id": f"eq.{book_id}",
                "status": "eq.generating",
                "select": "id",
            },
        )
        for chapter in stale:
            await db.update("chapters", {"status": "pending"}, {"id": chapter["id"]})

    return True


async def generate_next_pending_chapter(book_id: str) -> dict:
    """Legacy one-step generation entry point used by older clients."""
    await _reset_stale_generating_chapters(book_id)
    chapter = await _next_pending_chapter(book_id)
    tts_profile = await _resolve_book_tts_profile(book_id)
    if chapter is None:
        await _refresh_book_totals(book_id)
        status = await get_audio_status_payload(book_id)
        return {
            "done": True,
            "message": "All chapters complete",
            "status": status,
        }

    result = await _generate_single_chapter(book_id, chapter, tts_profile)
    status = await get_audio_status_payload(book_id)
    result["status_snapshot"] = status
    return result


# ══════════════════════════════════════════════════════════════════════
# MAIN GENERATION LOOP
# ══════════════════════════════════════════════════════════════════════

async def _run_generation_task(book_id: str) -> None:
    """Main generation loop. Processes chapters sequentially (each chapter
    uses parallel chunk processing internally for speed)."""
    consecutive_errors = 0
    max_consecutive_errors = 3
    tts_profile = await _resolve_book_tts_profile(book_id)

    # Notify SSE subscribers that audio generation has started
    event_bus.set_step(book_id, STEP_GENERATING, "Starting audio generation pipeline")

    try:
        while True:
            chapter = await _next_pending_chapter(book_id)
            if chapter is None:
                logger.info("All chapters processed for book %s", book_id)
                break

            result = await _generate_single_chapter(book_id, chapter, tts_profile)

            # Broadcast updated API usage after each chapter
            _emit_api_usage(book_id)

            if result.get("status") == "error":
                consecutive_errors += 1
                logger.warning(
                    "Chapter %s failed for book %s (%s consecutive errors)",
                    result.get("chapter_number"), book_id, consecutive_errors,
                )
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        "Stopping generation for book %s after %s consecutive failures",
                        book_id, consecutive_errors,
                    )
                    break
                # Brief pause before next chapter to let transient issues clear
                await asyncio.sleep(3)
            else:
                consecutive_errors = 0

    except asyncio.CancelledError:
        logger.info("Audio generation task cancelled for book %s", book_id)
        # Reset the chapter that was being generated back to pending
        stale = await db.select(
            "chapters",
            {
                "book_id": f"eq.{book_id}",
                "status": "eq.generating",
                "select": "id",
            },
        )
        for ch in stale:
            try:
                await db.update("chapters", {"status": "pending"}, {"id": ch["id"]})
            except Exception:
                pass
        raise
    except Exception:
        logger.exception("Audio generation crashed unexpectedly for book %s", book_id)
    finally:
        await _refresh_book_totals(book_id)
        _active_jobs.discard(book_id)
        _active_tasks.pop(book_id, None)
        _active_chapter_progress.pop(book_id, None)
        # Notify SSE subscribers that generation is complete
        event_bus.set_complete(book_id)


# ══════════════════════════════════════════════════════════════════════
# SINGLE CHAPTER GENERATION (now uses parallel chunk processing)
# ══════════════════════════════════════════════════════════════════════

async def _generate_single_chapter(
    book_id: str,
    chapter: dict,
    tts_profile: dict[str, str | None] | None = None,
) -> dict:
    """Generate audio for one chapter using parallel TTS chunk processing.

    HARD RULE: Only processes text from chapters that have been through the
    LLM or regex chapter generation pipeline. The text_content field must be
    populated from the chapters table — never from raw PDF extraction.
    """
    chapter_id = chapter["id"]
    chapter_number = chapter["chapter_number"]
    text = (chapter.get("text_content") or "").strip()

    # Verify this chapter has a title (evidence it came through chapter processing)
    chapter_title = chapter.get("title", "")
    if not chapter_title:
        logger.warning(
            "Chapter %s in book %s has no title — this may indicate raw text. Proceeding with caution.",
            chapter_number, book_id,
        )

    # Skip chapters with negligible text
    if len(text) < 10:
        await db.update(
            "chapters",
            {"status": "ready", "duration_seconds": 0, "audio_storage_path": None},
            {"id": chapter_id},
        )
        await _refresh_book_totals(book_id)
        return {
            "done": False,
            "chapter_number": chapter_number,
            "status": "skipped",
            "message": "Chapter skipped because it has no meaningful text.",
        }

    # Mark chapter as generating
    await db.update("chapters", {"status": "generating"}, {"id": chapter_id})

    # Initialize progress tracking for this chapter
    _active_chapter_progress[book_id] = {"completed_chunks": 0, "total_chunks": 0}

    # Notify SSE subscribers about chapter start
    chapter_title = chapter.get("title", f"Chapter {chapter_number}")
    event_bus.set_chapter_start(book_id, chapter_number, chapter_title, len(text))
    chapter_start_time = time.time()

    try:
        # Progress callback — updates the in-memory tracker AND SSE event bus
        def on_chunk_complete(completed: int, total: int) -> None:
            _active_chapter_progress[book_id] = {
                "completed_chunks": completed,
                "total_chunks": total,
            }
            event_bus.set_chunk_progress(book_id, completed, total)

        source_language = (tts_profile or {}).get("source_language") or "en"
        requested_target = (tts_profile or {}).get("translation_target_language")
        translation_result = await maybe_translate_for_tts(
            text=text,
            source_language=source_language,
            requested_target=requested_target,
        )

        logger.info(
            (
                "Starting parallel TTS for chapter %s, book %s "
                "(chars=%d, detected_language=%s, translation_applied=%s, tts_language=%s)"
            ),
            chapter_number,
            book_id,
            len(text),
            source_language,
            translation_result.applied,
            translation_result.tts_language,
        )

        # generate_chapter_audio handles chunking + parallel processing internally
        final_mp3 = await generate_chapter_audio(
            text=translation_result.text,
            on_chunk_complete=on_chunk_complete,
            language=translation_result.tts_language,
        )

        if len(final_mp3) < 256:
            raise ValueError("Final audio is too small — generation likely failed")

        duration = get_audio_duration_seconds(final_mp3)
        storage_path = f"{book_id}/chapter_{chapter_number}.mp3"

        # Upload to Supabase Storage
        await db.upload_file("audiobooks", storage_path, final_mp3, "audio/mpeg")
        await db.update(
            "chapters",
            {
                "audio_storage_path": storage_path,
                "duration_seconds": duration,
                "status": "ready",
            },
            {"id": chapter_id},
        )
        await _refresh_book_totals(book_id)

        chapter_duration_elapsed = int(time.time() - chapter_start_time)
        logger.info(
            "Chapter %s complete for book %s (%ss audio)",
            chapter_number, book_id, duration,
        )

        # Notify SSE subscribers about chapter completion
        event_bus.set_chapter_done(book_id, chapter_number, "ready", duration=chapter_duration_elapsed)

        return {
            "done": False,
            "chapter_number": chapter_number,
            "status": "ready",
            "duration": duration,
        }

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        chapter_duration_elapsed = int(time.time() - chapter_start_time)
        logger.warning(
            "Chapter %s generation failed for book %s: %s",
            chapter_number, book_id, exc,
        )
        try:
            await db.update(
                "chapters",
                {"status": "error", "duration_seconds": 0, "audio_storage_path": None},
                {"id": chapter_id},
            )
            await _refresh_book_totals(book_id)
        except Exception as db_exc:
            logger.error("Failed to update chapter status to error: %s", db_exc)

        # Notify SSE subscribers about chapter failure
        event_bus.set_chapter_done(
            book_id, chapter_number, "error",
            duration=chapter_duration_elapsed, error=str(exc),
        )

        return {
            "done": False,
            "chapter_number": chapter_number,
            "status": "error",
            "error": str(exc),
        }
    finally:
        _active_chapter_progress.pop(book_id, None)


# ══════════════════════════════════════════════════════════════════════
# API USAGE EVENT HELPER
# ══════════════════════════════════════════════════════════════════════

def _emit_api_usage(book_id: str) -> None:
    """Broadcast current TTS + LLM API usage stats to SSE subscribers."""
    try:
        tts = get_tts_stats()
        llm = get_llm_stats()
        event_bus.set_api_usage(book_id, {
            "elevenlabs_chars_used": tts.get("elevenlabs_total_chars_used", 0),
            "elevenlabs_chars_remaining": tts.get("elevenlabs_total_chars_remaining", 0),
            "elevenlabs_all_exhausted": tts.get("elevenlabs_all_exhausted", False),
            "elevenlabs_active_provider": tts.get("active_provider", "unknown"),
            "elevenlabs_keys": tts.get("elevenlabs", []),
            "gemini_input_tokens": llm.get("total_input_tokens", 0),
            "gemini_output_tokens": llm.get("total_output_tokens", 0),
            "gemini_total_requests": llm.get("total_requests", 0),
            "gemini_failed_requests": llm.get("failed_requests", 0),
        })
    except Exception as exc:
        logger.debug("Failed to emit API usage: %s", exc)


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

async def _reset_stale_generating_chapters(book_id: str) -> None:
    stale = await db.select(
        "chapters",
        {
            "book_id": f"eq.{book_id}",
            "status": "eq.generating",
            "select": "id",
        },
    )
    for chapter in stale:
        await db.update("chapters", {"status": "pending"}, {"id": chapter["id"]})


async def _resolve_book_tts_profile(book_id: str) -> dict[str, str | None]:
    """Resolve source + translation target language for chapter TTS."""
    source_language = "en"
    translation_target_language: str | None = None

    try:
        rows = await db.select(
            "books",
            {
                "id": f"eq.{book_id}",
                "select": "language,translation_target_language",
                "limit": "1",
            },
        )
        if rows:
            source_language = (rows[0].get("language") or "en").strip().lower() or "en"
            raw_target = rows[0].get("translation_target_language")
            if raw_target is not None:
                normalized = str(raw_target).strip().lower()
                translation_target_language = normalized or None
            return {
                "source_language": source_language,
                "translation_target_language": translation_target_language,
            }
    except Exception as exc:
        logger.debug("Unable to resolve translation target for book %s: %s", book_id, exc)

    try:
        rows = await db.select(
            "books",
            {
                "id": f"eq.{book_id}",
                "select": "language",
                "limit": "1",
            },
        )
        if rows:
            source_language = (rows[0].get("language") or "en").strip().lower() or "en"
    except Exception as exc:
        logger.debug("Unable to resolve language for book %s: %s", book_id, exc)

    return {
        "source_language": source_language,
        "translation_target_language": None,
    }


async def _next_pending_chapter(book_id: str) -> dict | None:
    pending = await db.select(
        "chapters",
        {
            "book_id": f"eq.{book_id}",
            "status": "eq.pending",
            "order": "chapter_number.asc",
            "limit": "1",
            "select": DETAIL_SELECT,
        },
    )
    if not pending:
        return None
    return pending[0]


async def get_enhanced_status(book_id: str) -> dict:
    """Return the standard audio status payload enriched with pipeline state and API usage."""
    payload = await get_audio_status_payload(book_id)
    bus_state = event_bus.get_state(book_id)
    tts = get_tts_stats()
    llm = get_llm_stats()

    payload["pipeline"] = {
        "step": bus_state["step"],
        "current_chapter": bus_state["current_chapter"],
        "current_chapter_title": bus_state["current_chapter_title"],
        "chunk_progress": bus_state["chunk_progress"],
    }
    payload["api_usage"] = {
        "elevenlabs": {
            "chars_used": tts.get("elevenlabs_total_chars_used", 0),
            "chars_remaining": tts.get("elevenlabs_total_chars_remaining", 0),
            "all_exhausted": tts.get("elevenlabs_all_exhausted", False),
            "active_provider": tts.get("active_provider", "unknown"),
            "keys": tts.get("elevenlabs", []),
        },
        "gemini": {
            "input_tokens": llm.get("total_input_tokens", 0),
            "output_tokens": llm.get("total_output_tokens", 0),
            "total_requests": llm.get("total_requests", 0),
            "failed_requests": llm.get("failed_requests", 0),
        },
    }
    return payload


async def _refresh_book_totals(book_id: str) -> None:
    try:
        chapters = await db.select(
            "chapters",
            {
                "book_id": f"eq.{book_id}",
                "select": "status,duration_seconds",
            },
        )
        if not chapters:
            return

        total_duration = sum(
            chapter.get("duration_seconds", 0)
            for chapter in chapters
            if chapter["status"] == "ready"
        )
        await db.update(
            "books",
            {"total_duration_seconds": total_duration},
            {"id": book_id},
        )
    except Exception as exc:
        logger.error("Failed to refresh book totals for %s: %s", book_id, exc)
