"""Audibuddy Backend - FastAPI Application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.core.config import settings
from app.core.database import db
from app.services.tts_service import close_tts_client
from app.services.translation_service import close_translation_client
from app.services.llm_chapter_service import close_llm_client
from app.api.routes import books, chapters, audio, progress, recommendations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown."""
    logger.info("Audibuddy API starting up")
    yield
    # Clean up all persistent HTTP connection pools on shutdown
    logger.info("Audibuddy API shutting down — closing clients")
    await db.close()
    await close_tts_client()
    await close_translation_client()
    await close_llm_client()


app = FastAPI(
    title="Audibuddy API",
    description="Audibuddy - PDF-to-Audiobook Backend API",
    version="0.2.0",
    lifespan=lifespan,
)

# GZip compression for API responses (big win for JSON payloads with chapter lists)
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS middleware (allows frontend to talk to backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(books.router, prefix="/api")
app.include_router(chapters.router, prefix="/api")
app.include_router(audio.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")


@app.get("/")
def root():
    return {"message": "Welcome to Audibuddy API", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/admin/status")
def admin_status():
    """Returns whether admin mode is enabled. Used by the frontend to show/hide admin features."""
    return {"admin": settings.ADMIN_MODE}
