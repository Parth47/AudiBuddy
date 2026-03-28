"""Chapter-related API endpoints."""

from fastapi import APIRouter, HTTPException
from app.core.database import db
from app.schemas.chapter import ChapterResponse, ChapterDetailResponse

router = APIRouter(prefix="/chapters", tags=["chapters"])


@router.get("/book/{book_id}", response_model=list[ChapterResponse])
async def list_chapters(book_id: str):
    """List all chapters for a book, ordered by chapter number."""
    chapters = await db.select("chapters", {
        "book_id": f"eq.{book_id}",
        "order": "chapter_number.asc",
        "select": "id,book_id,chapter_number,title,duration_seconds,status,created_at",
    })
    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found for this book")
    return chapters


@router.get("/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter(chapter_id: str):
    """Get a single chapter with full text content."""
    chapters = await db.select("chapters", {"id": f"eq.{chapter_id}"})
    if not chapters:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapters[0]
