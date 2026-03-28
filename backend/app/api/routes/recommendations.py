"""Recommendation and discovery endpoints."""

from fastapi import APIRouter, Header
from app.core.database import db
from app.schemas.book import BookResponse

router = APIRouter(prefix="/discover", tags=["discover"])


@router.get("/genres")
async def list_genres():
    """Get all genres that have at least one ready book."""
    books = await db.select("books", {
        "status": "eq.ready",
        "select": "genre",
    })
    genres = sorted(set(b["genre"] for b in books if b.get("genre")))
    return {"genres": genres}


@router.get("/featured", response_model=list[BookResponse])
async def featured_books():
    """Get featured books for the hero banner (latest 5 books)."""
    books = await db.select("books", {
        "status": "eq.ready",
        "order": "created_at.desc",
        "limit": "5",
    })
    return books


@router.get("/by-genre/{genre}", response_model=list[BookResponse])
async def books_by_genre(genre: str, limit: int = 10):
    """Get books for a specific genre (for horizontal scroll rows)."""
    books = await db.select("books", {
        "status": "eq.ready",
        "genre": f"eq.{genre}",
        "order": "created_at.desc",
        "limit": str(limit),
    })
    return books


@router.get("/recent", response_model=list[BookResponse])
async def recent_books(limit: int = 10):
    """Get recently added books."""
    books = await db.select("books", {
        "status": "eq.ready",
        "order": "created_at.desc",
        "limit": str(limit),
    })
    return books


@router.get("/similar/{book_id}", response_model=list[BookResponse])
async def similar_books(book_id: str, limit: int = 6):
    """
    Get books similar to the given book.
    For now: same genre. Later: embedding similarity.
    """
    # Get the source book's genre
    books = await db.select("books", {"id": f"eq.{book_id}"})
    if not books:
        return []

    genre = books[0].get("genre", "General")

    # Find other books in the same genre
    similar = await db.select("books", {
        "status": "eq.ready",
        "genre": f"eq.{genre}",
        "id": f"neq.{book_id}",
        "order": "created_at.desc",
        "limit": str(limit),
    })
    return similar
