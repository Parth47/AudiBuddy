"""User progress and favorites endpoints."""

from fastapi import APIRouter, HTTPException, Header
from app.core.database import db
from app.schemas.progress import ProgressUpdate, ProgressResponse, FavoriteResponse

router = APIRouter(tags=["user"])


# --- Helper to extract user ID from Supabase Auth token ---

async def get_user_id(authorization: str = Header(...)) -> str:
    """
    Extract user_id from Supabase JWT token.
    The frontend sends: Authorization: Bearer <token>
    We verify it by calling Supabase Auth API.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization.replace("Bearer ", "")

    try:
        import httpx
        resp = await httpx.AsyncClient().get(
            f"{db.url}/auth/v1/user",
            headers={
                "apikey": db.headers["apikey"],
                "Authorization": f"Bearer {token}",
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user = resp.json()
        return user["id"]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed")


# --- Progress Endpoints ---

@router.get("/progress/{book_id}", response_model=ProgressResponse | None)
async def get_progress(book_id: str, authorization: str = Header(...)):
    """Get the user's listening progress for a specific book."""
    user_id = await get_user_id(authorization)

    rows = await db.select("user_progress", {
        "user_id": f"eq.{user_id}",
        "book_id": f"eq.{book_id}",
    })
    if not rows:
        return None
    return rows[0]


@router.put("/progress/{book_id}", response_model=ProgressResponse)
async def update_progress(
    book_id: str,
    data: ProgressUpdate,
    authorization: str = Header(...),
):
    """Update (or create) the user's listening progress for a book."""
    user_id = await get_user_id(authorization)

    # Check if progress record exists
    existing = await db.select("user_progress", {
        "user_id": f"eq.{user_id}",
        "book_id": f"eq.{book_id}",
    })

    progress_data = {
        "chapter_id": data.chapter_id,
        "progress_seconds": data.progress_seconds,
        "completed": data.completed,
        "last_played_at": "now()",
    }

    if existing:
        rows = await db.update(
            "user_progress",
            progress_data,
            {"user_id": user_id, "book_id": book_id},
        )
    else:
        progress_data["user_id"] = user_id
        progress_data["book_id"] = book_id
        rows = await db.insert("user_progress", progress_data)

    return rows[0]


@router.get("/progress", response_model=list[ProgressResponse])
async def list_progress(authorization: str = Header(...)):
    """Get all progress records for the current user (for 'Continue Listening' row)."""
    user_id = await get_user_id(authorization)

    rows = await db.select("user_progress", {
        "user_id": f"eq.{user_id}",
        "order": "last_played_at.desc",
        "limit": "20",
    })
    return rows


# --- Favorites Endpoints ---

@router.get("/favorites", response_model=list[FavoriteResponse])
async def list_favorites(authorization: str = Header(...)):
    """Get all favorites for the current user."""
    user_id = await get_user_id(authorization)

    rows = await db.select("favorites", {
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
    })
    return rows


@router.post("/favorites/{book_id}", response_model=FavoriteResponse)
async def add_favorite(book_id: str, authorization: str = Header(...)):
    """Add a book to favorites."""
    user_id = await get_user_id(authorization)

    # Check if already favorited
    existing = await db.select("favorites", {
        "user_id": f"eq.{user_id}",
        "book_id": f"eq.{book_id}",
    })
    if existing:
        return existing[0]

    rows = await db.insert("favorites", {
        "user_id": user_id,
        "book_id": book_id,
    })
    return rows[0]


@router.delete("/favorites/{book_id}")
async def remove_favorite(book_id: str, authorization: str = Header(...)):
    """Remove a book from favorites."""
    user_id = await get_user_id(authorization)

    await db.delete("favorites", {
        "user_id": user_id,
        "book_id": book_id,
    })
    return {"message": "Favorite removed"}
