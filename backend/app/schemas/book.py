"""Pydantic schemas for Book-related requests and responses."""

from datetime import datetime
from pydantic import BaseModel


class BookBase(BaseModel):
    title: str
    author: str = "Unknown"
    description: str | None = None
    genre: str = "General"
    language: str = "en"
    translation_target_language: str | None = None


class BookCreate(BookBase):
    """Used when uploading a new book (PDF)."""
    pass


class BookResponse(BookBase):
    """Returned when listing/fetching books."""
    id: str
    cover_image_url: str | None = None
    total_chapters: int = 0
    total_duration_seconds: int = 0
    status: str = "processing"
    created_at: datetime
    updated_at: datetime


class BookListResponse(BaseModel):
    """Paginated book list."""
    books: list[BookResponse]
    total: int
