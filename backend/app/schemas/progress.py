"""Pydantic schemas for user progress and favorites."""

from datetime import datetime
from pydantic import BaseModel


class ProgressUpdate(BaseModel):
    """Sent by the frontend to update listening progress."""
    chapter_id: str
    progress_seconds: float
    completed: bool = False


class ProgressResponse(BaseModel):
    """Returned when fetching user's progress on a book."""
    id: str
    user_id: str
    book_id: str
    chapter_id: str
    progress_seconds: float
    completed: bool
    last_played_at: datetime


class FavoriteResponse(BaseModel):
    """Returned when listing user's favorites."""
    id: str
    user_id: str
    book_id: str
    created_at: datetime
