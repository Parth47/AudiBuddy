"""Pydantic schemas for Chapter-related requests and responses."""

from datetime import datetime
from pydantic import BaseModel


class ChapterResponse(BaseModel):
    """Returned when listing chapters of a book."""
    id: str
    book_id: str
    chapter_number: int
    title: str
    duration_seconds: int = 0
    status: str = "pending"
    created_at: datetime


class ChapterDetailResponse(ChapterResponse):
    """Returned when fetching a single chapter (includes text)."""
    text_content: str | None = None
    audio_storage_path: str | None = None
