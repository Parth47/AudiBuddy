"""Shared pytest fixtures for AudiBuddy backend tests."""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure the backend root is on sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


# ── Fake settings for tests (avoids loading real .env) ─────────────────

class FakeSettings:
    """Minimal settings object for tests. Override individual attrs as needed."""
    ADMIN_MODE = True
    SUPABASE_URL = "https://fake.supabase.co"
    SUPABASE_KEY = "fake-key"
    ELEVENLABS_API_KEYS = []
    OPENAI_TTS_API_KEYS = []
    ELEVENLABS_VOICE_ID = "test-voice"
    ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
    ELEVENLABS_MULTILINGUAL_MODEL_ID = "eleven_multilingual_v2"
    ELEVENLABS_VOICE_ID_HI = "test-voice-hi"
    ELEVENLABS_VOICE_ID_MR = "test-voice-mr"
    ELEVENLABS_MONTHLY_CHAR_LIMIT = 10000
    ELEVENLABS_TRANSLATION_ENABLED = True
    ELEVENLABS_TRANSLATION_DEFAULT_TARGET = "en"
    ELEVENLABS_TRANSLATION_SOURCE_LANGS = ["hi", "mr"]
    ELEVENLABS_TRANSLATION_MAX_CHARS = 1100
    ELEVENLABS_TRANSLATION_RETRIES = 2
    ELEVENLABS_TRANSLATION_TIMEOUT_SECONDS = 240
    ELEVENLABS_TRANSLATION_POLL_INTERVAL_SECONDS = 2.0
    ELEVENLABS_TRANSLATION_DELETE_DUB = True
    ELEVENLABS_TRANSLATION_FALLBACK_TO_SOURCE = True
    OPENAI_TTS_MODEL = "tts-1"
    OPENAI_TTS_VOICE = "alloy"
    EDGE_TTS_VOICE = "en-US-GuyNeural"
    EDGE_TTS_VOICE_HI = "hi-IN-SwaraNeural"
    EDGE_TTS_VOICE_MR = "mr-IN-AarohiNeural"
    TTS_CHUNK_SIZE = 1500
    TTS_PARALLEL_CHUNKS = 3
    TTS_PROVIDER_ORDER = ["elevenlabs", "openai", "edge"]
    GOOGLE_GEMINI_API_KEYS = []
    OPENAI_LLM_API_KEYS = []
    ANTHROPIC_API_KEYS = []
    LLM_PROVIDER_ORDER = ["gemini", "openai", "anthropic"]
    GEMINI_MODEL = "gemini-2.0-flash"
    OPENAI_LLM_MODEL = "gpt-4o-mini"
    ANTHROPIC_MODEL = "claude-3-haiku-20240307"
    AUDIO_OUTPUT_DIR = "/tmp/audibuddy_test_output"
    PDF_OCR_ENABLED = False
    PDF_OCR_LANGUAGES = "hin+mar+eng"
    PDF_OCR_DPI = 300
    PDF_OCR_MIN_PAGE_CHARS = 20


@pytest.fixture
def fake_settings():
    return FakeSettings()


@pytest.fixture
def mock_db():
    """A mock database client that returns empty results by default."""
    db = MagicMock()
    db.select = AsyncMock(return_value=[])
    db.insert = AsyncMock(return_value=[])
    db.update = AsyncMock(return_value=[])
    db.get_public_url = MagicMock(return_value="https://fake.storage/audio.mp3")
    db.upload_file = AsyncMock(return_value="audio/test.mp3")
    return db
