"""Book-related API endpoints."""

import asyncio
import logging
from urllib.parse import unquote

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from app.core.config import settings
from app.core.database import db
from app.services.audio_generation import cancel_audio_generation
from app.services.pdf_service import process_pdf, LLMProcessingError
from app.schemas.book import BookResponse, BookListResponse

router = APIRouter(prefix="/books", tags=["books"])
logger = logging.getLogger(__name__)


def require_admin():
    """Dependency that blocks write operations when ADMIN_MODE is off."""
    if not settings.ADMIN_MODE:
        raise HTTPException(
            status_code=403,
            detail="This action is only available for the developer. Admin mode is not enabled.",
        )
    return True


def _cover_storage_path(cover_image_url: str | None) -> str | None:
    if not cover_image_url:
        return None

    marker = "/object/public/covers/"
    if marker not in cover_image_url:
        return None

    return unquote(cover_image_url.split(marker, 1)[1])


async def _cleanup_storage_assets(files_to_delete: list[tuple[str, str]]) -> None:
    grouped_paths: dict[str, list[str]] = {}
    for bucket, path in files_to_delete:
        grouped_paths.setdefault(bucket, []).append(path)

    for bucket, paths in grouped_paths.items():
        try:
            await db.delete_files(bucket, paths, ignore_missing=True)
        except Exception as exc:
            logger.warning("Failed to delete storage assets from %s: %s", bucket, exc)


@router.post("/upload", response_model=BookResponse, dependencies=[Depends(require_admin)])
async def upload_book(
    file: UploadFile = File(...),
    title: str = Form(...),
    author: str = Form("Unknown"),
    genre: str = Form("General"),
    description: str = Form(""),
    cover_image: UploadFile | None = File(None),
    use_fallback: bool = Form(False),
):
    """
    Upload a PDF and process it into chapters.
    Optionally upload a cover image.
    If use_fallback is True, skips LLM and uses regex-based chapter detection.
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Read the file
    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    # 1. Create book record (status = processing)
    book_data = {
        "title": title,
        "author": author,
        "genre": genre,
        "description": description or f"Audiobook of {title} by {author}",
        "status": "processing",
    }
    book_rows = await db.insert("books", book_data)
    book = book_rows[0]
    book_id = book["id"]

    try:
        # 2. Upload PDF to storage
        storage_path = f"{book_id}/{file.filename}"
        await db.upload_file("pdfs", storage_path, pdf_bytes, "application/pdf")
        await db.update("books", {"pdf_storage_path": storage_path}, {"id": book_id})

        # 3. Upload cover image if provided
        cover_image_url = None
        if cover_image and cover_image.filename:
            cover_bytes = await cover_image.read()
            if len(cover_bytes) > 0:
                ext = cover_image.filename.lower().rsplit(".", 1)[-1] if "." in cover_image.filename else "jpg"
                content_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
                content_type = content_types.get(ext, "image/jpeg")

                cover_path = f"{book_id}/cover.{ext}"
                await db.upload_file("covers", cover_path, cover_bytes, content_type)
                cover_image_url = db.get_public_url("covers", cover_path)
                await db.update("books", {"cover_image_url": cover_image_url}, {"id": book_id})

        # 4. Extract text and detect chapters
        try:
            chapters = await process_pdf(pdf_bytes, use_fallback=use_fallback)
        except LLMProcessingError as llm_err:
            # LLM failed — return special status so frontend can offer fallback
            await db.update("books", {"status": "llm_failed"}, {"id": book_id})
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "llm_processing_failed",
                    "message": f"LLM processing failed: {llm_err}. Do you want to use the fallback mechanism?",
                    "book_id": book_id,
                    "can_retry_with_fallback": True,
                },
            )

        # 5. Store chapters in DB
        for i, chapter in enumerate(chapters):
            chapter_data = {
                "book_id": book_id,
                "chapter_number": i + 1,
                "title": chapter["title"][:200],
                "text_content": chapter["text"],
                "status": "pending",
            }
            await db.insert("chapters", chapter_data)

        # 6. Update book status and chapter count
        update_data = {"status": "ready", "total_chapters": len(chapters)}
        if cover_image_url:
            update_data["cover_image_url"] = cover_image_url
        updated = await db.update("books", update_data, {"id": book_id})
        return updated[0]

    except HTTPException:
        raise
    except Exception as e:
        await db.update("books", {"status": "error"}, {"id": book_id})
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.post("/retry-fallback/{book_id}", response_model=BookResponse, dependencies=[Depends(require_admin)])
async def retry_with_fallback(book_id: str):
    """Retry chapter processing using regex fallback for a book that failed LLM processing."""
    books = await db.select("books", {"id": f"eq.{book_id}"})
    if not books:
        raise HTTPException(status_code=404, detail="Book not found")

    book = books[0]
    if book["status"] not in ("llm_failed", "error"):
        raise HTTPException(status_code=400, detail="Book is not in a failed state")

    pdf_path = book.get("pdf_storage_path")
    if not pdf_path:
        raise HTTPException(status_code=400, detail="No PDF found for this book")

    try:
        # Download PDF from storage
        pdf_bytes = await db.download_file("pdfs", pdf_path)

        # Process with fallback (regex-only)
        chapters = await process_pdf(pdf_bytes, use_fallback=True)

        # Clear existing chapters
        existing = await db.select("chapters", {"book_id": f"eq.{book_id}"})
        if existing:
            await db.delete("chapters", {"book_id": book_id})

        # Store new chapters
        for i, chapter in enumerate(chapters):
            chapter_data = {
                "book_id": book_id,
                "chapter_number": i + 1,
                "title": chapter["title"][:200],
                "text_content": chapter["text"],
                "status": "pending",
            }
            await db.insert("chapters", chapter_data)

        updated = await db.update(
            "books",
            {"status": "ready", "total_chapters": len(chapters)},
            {"id": book_id},
        )
        return updated[0]

    except Exception as e:
        await db.update("books", {"status": "error"}, {"id": book_id})
        raise HTTPException(status_code=500, detail=f"Fallback processing failed: {str(e)}")


@router.patch("/{book_id}/metadata", response_model=BookResponse, dependencies=[Depends(require_admin)])
async def update_book_metadata(
    book_id: str,
    genre: str | None = Form(None),
    cover_image: UploadFile | None = File(None),
):
    """Update book metadata (genre and/or cover image)."""
    books = await db.select("books", {"id": f"eq.{book_id}"})
    if not books:
        raise HTTPException(status_code=404, detail="Book not found")

    update_data: dict = {}

    if genre is not None:
        update_data["genre"] = genre

    if cover_image and cover_image.filename:
        cover_bytes = await cover_image.read()
        if len(cover_bytes) > 0:
            ext = cover_image.filename.lower().rsplit(".", 1)[-1] if "." in cover_image.filename else "jpg"
            content_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
            content_type = content_types.get(ext, "image/jpeg")

            cover_path = f"{book_id}/cover.{ext}"
            await db.upload_file("covers", cover_path, cover_bytes, content_type)
            cover_image_url = db.get_public_url("covers", cover_path)
            update_data["cover_image_url"] = cover_image_url

    if not update_data:
        return books[0]

    updated = await db.update("books", update_data, {"id": book_id})
    return updated[0]


@router.get("", response_model=BookListResponse)
async def list_books(
    genre: str | None = None,
    status: str = "ready",
    limit: int = 20,
    offset: int = 0,
):
    """List all books, optionally filtered by genre."""
    params = {
        "status": f"eq.{status}",
        "order": "created_at.desc",
        "limit": str(limit),
        "offset": str(offset),
    }
    if genre:
        params["genre"] = f"eq.{genre}"

    books = await db.select("books", params)

    count_params = {"status": f"eq.{status}"}
    if genre:
        count_params["genre"] = f"eq.{genre}"
    all_books = await db.select("books", count_params)

    return BookListResponse(books=books, total=len(all_books))


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: str):
    """Get a single book by ID."""
    books = await db.select("books", {"id": f"eq.{book_id}"})
    if not books:
        raise HTTPException(status_code=404, detail="Book not found")
    return books[0]


@router.delete("/{book_id}", dependencies=[Depends(require_admin)])
async def delete_book(book_id: str):
    """Delete a book, its related records, and associated storage assets."""
    books = await db.select(
        "books",
        {
            "id": f"eq.{book_id}",
            "select": "id,title,pdf_storage_path,cover_image_url",
            "limit": "1",
        },
    )
    if not books:
        raise HTTPException(status_code=404, detail="Book not found")

    book = books[0]
    chapters = await db.select(
        "chapters",
        {
            "book_id": f"eq.{book_id}",
            "select": "audio_storage_path",
        },
    )

    await cancel_audio_generation(book_id)

    files_to_delete: list[tuple[str, str]] = []
    if book.get("pdf_storage_path"):
        files_to_delete.append(("pdfs", book["pdf_storage_path"]))

    cover_path = _cover_storage_path(book.get("cover_image_url"))
    if cover_path:
        files_to_delete.append(("covers", cover_path))

    for chapter in chapters:
        audio_path = chapter.get("audio_storage_path")
        if audio_path:
            files_to_delete.append(("audiobooks", audio_path))

    unique_files = list(dict.fromkeys(files_to_delete))
    await db.delete("books", {"id": book_id})
    if unique_files:
        asyncio.create_task(_cleanup_storage_assets(unique_files))

    return {
        "deleted": True,
        "book_id": book_id,
        "title": book["title"],
        "removed_files": len(unique_files),
        "storage_cleanup_complete": True,
        "storage_warnings": [],
    }
