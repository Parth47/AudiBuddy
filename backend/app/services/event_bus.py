"""In-memory event bus for Server-Sent Events (SSE).

Allows the audio generation pipeline to push real-time events that the
frontend can consume via an SSE endpoint.  Each book_id has its own
channel with multiple subscribers (browser tabs).

Event types:
  - step_change    : Pipeline step changed (extracting → structuring → generating)
  - chapter_start  : A chapter started generating
  - chunk_progress : Sub-chapter chunk completed
  - chapter_done   : A chapter finished (ready or error)
  - api_usage      : Updated API usage stats
  - complete       : All chapters done
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Pipeline step constants ───────────────────────────────────────────

STEP_IDLE = "idle"
STEP_EXTRACTING = "extracting_pdf"
STEP_STRUCTURING = "structuring_chapters"
STEP_GENERATING = "generating_audio"
STEP_COMPLETE = "complete"


@dataclass
class _BookChannel:
    """Event channel for a single book."""
    queues: list[asyncio.Queue] = field(default_factory=list)
    current_step: str = STEP_IDLE
    current_chapter: int | None = None
    current_chapter_title: str = ""
    chunk_progress: dict = field(default_factory=lambda: {"completed": 0, "total": 0})
    api_usage: dict = field(default_factory=dict)
    last_event_time: float = 0.0


class EventBus:
    """Global event bus — one instance shared across the app."""

    def __init__(self) -> None:
        self._channels: dict[str, _BookChannel] = {}

    def _get_channel(self, book_id: str) -> _BookChannel:
        if book_id not in self._channels:
            self._channels[book_id] = _BookChannel()
        return self._channels[book_id]

    # ── Subscribe / unsubscribe ───────────────────────────────────────

    def subscribe(self, book_id: str) -> asyncio.Queue:
        """Create a new subscriber queue for a book. Returns the queue."""
        channel = self._get_channel(book_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        channel.queues.append(queue)

        # Immediately send current state as a "snapshot" event
        snapshot = self._snapshot(book_id)
        try:
            queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            pass

        return queue

    def unsubscribe(self, book_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        channel = self._channels.get(book_id)
        if channel:
            try:
                channel.queues.remove(queue)
            except ValueError:
                pass
            # Garbage-collect empty channels
            if not channel.queues:
                self._channels.pop(book_id, None)

    # ── Publish events ────────────────────────────────────────────────

    def emit(self, book_id: str, event_type: str, data: dict | None = None) -> None:
        """Push an event to all subscribers of a book."""
        channel = self._get_channel(book_id)
        channel.last_event_time = time.time()

        event = {
            "type": event_type,
            "timestamp": channel.last_event_time,
            "data": data or {},
        }

        dead_queues = []
        for queue in channel.queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead_queues.append(queue)

        # Remove dead/full queues
        for q in dead_queues:
            try:
                channel.queues.remove(q)
            except ValueError:
                pass

    def set_step(self, book_id: str, step: str, detail: str = "") -> None:
        """Update the pipeline step and notify subscribers."""
        channel = self._get_channel(book_id)
        channel.current_step = step
        self.emit(book_id, "step_change", {"step": step, "detail": detail})

    def set_chapter_start(self, book_id: str, chapter_number: int, title: str, total_chars: int) -> None:
        channel = self._get_channel(book_id)
        channel.current_chapter = chapter_number
        channel.current_chapter_title = title
        channel.chunk_progress = {"completed": 0, "total": 0}
        self.emit(book_id, "chapter_start", {
            "chapter_number": chapter_number,
            "title": title,
            "total_chars": total_chars,
        })

    def set_chunk_progress(self, book_id: str, completed: int, total: int) -> None:
        channel = self._get_channel(book_id)
        channel.chunk_progress = {"completed": completed, "total": total}
        self.emit(book_id, "chunk_progress", {
            "completed": completed,
            "total": total,
            "chapter_number": channel.current_chapter,
        })

    def set_chapter_done(self, book_id: str, chapter_number: int, status: str, duration: int = 0, error: str = "") -> None:
        channel = self._get_channel(book_id)
        channel.current_chapter = None
        channel.chunk_progress = {"completed": 0, "total": 0}
        self.emit(book_id, "chapter_done", {
            "chapter_number": chapter_number,
            "status": status,
            "duration": duration,
            "error": error,
        })

    def set_api_usage(self, book_id: str, usage: dict) -> None:
        """Update cumulative API usage stats for a book."""
        channel = self._get_channel(book_id)
        # Merge into existing usage
        for key, val in usage.items():
            if isinstance(val, (int, float)) and key in channel.api_usage:
                channel.api_usage[key] = channel.api_usage[key] + val
            else:
                channel.api_usage[key] = val
        self.emit(book_id, "api_usage", channel.api_usage)

    def set_complete(self, book_id: str) -> None:
        channel = self._get_channel(book_id)
        channel.current_step = STEP_COMPLETE
        self.emit(book_id, "complete", {})

    # ── Snapshot (current state) ──────────────────────────────────────

    def _snapshot(self, book_id: str) -> dict:
        channel = self._get_channel(book_id)
        return {
            "type": "snapshot",
            "timestamp": time.time(),
            "data": {
                "step": channel.current_step,
                "current_chapter": channel.current_chapter,
                "current_chapter_title": channel.current_chapter_title,
                "chunk_progress": channel.chunk_progress,
                "api_usage": channel.api_usage,
            },
        }

    def get_state(self, book_id: str) -> dict:
        """Return current pipeline state (for polling fallback)."""
        channel = self._get_channel(book_id)
        return {
            "step": channel.current_step,
            "current_chapter": channel.current_chapter,
            "current_chapter_title": channel.current_chapter_title,
            "chunk_progress": channel.chunk_progress,
            "api_usage": channel.api_usage,
        }

    def cleanup(self, book_id: str) -> None:
        """Remove a book's channel entirely."""
        self._channels.pop(book_id, None)


# Global singleton
event_bus = EventBus()
