"""Application configuration loaded from environment variables.

Supports multiple API keys (comma-separated) for automatic rotation.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _parse_key_list(env_var: str) -> list[str]:
    """Parse a comma-separated list of API keys from an environment variable.
    Strips whitespace and drops empty values."""
    raw = os.getenv(env_var, "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _parse_bool(env_var: str, default: str = "false") -> bool:
    """Parse a boolean env var using common truthy values."""
    return os.getenv(env_var, default).strip().lower() in ("true", "1", "yes", "on")


def _parse_csv(env_var: str, default: str = "") -> list[str]:
    """Parse a comma-separated env var into a clean lowercase list."""
    raw = os.getenv(env_var, default)
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


class Settings:
    # ── Admin mode ──────────────────────────────────────────────────
    # Set to "true" when running locally. When False, upload/edit/delete
    # endpoints are disabled so the public deployment is read-only.
    ADMIN_MODE: bool = _parse_bool("ADMIN_MODE", "false")

    # ── Supabase ──────────────────────────────────────────────────────
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # ── CORS ──────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

    # ── TTS — ElevenLabs (primary) ────────────────────────────────────
    # Accepts comma-separated keys for rotation: "key1,key2,key3"
    ELEVENLABS_API_KEYS: list[str] = _parse_key_list("ELEVENLABS_API_KEYS")
    ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # "Rachel"
    ELEVENLABS_MODEL_ID: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2")
    ELEVENLABS_MULTILINGUAL_MODEL_ID: str = os.getenv("ELEVENLABS_MULTILINGUAL_MODEL_ID", "eleven_multilingual_v2")
    ELEVENLABS_VOICE_ID_HI: str = os.getenv("ELEVENLABS_VOICE_ID_HI", ELEVENLABS_VOICE_ID)
    ELEVENLABS_VOICE_ID_MR: str = os.getenv("ELEVENLABS_VOICE_ID_MR", ELEVENLABS_VOICE_ID_HI)
    ELEVENLABS_MONTHLY_CHAR_LIMIT: int = int(os.getenv("ELEVENLABS_MONTHLY_CHAR_LIMIT", "10000"))
    ELEVENLABS_TRANSLATION_ENABLED: bool = _parse_bool("ELEVENLABS_TRANSLATION_ENABLED", "true")
    ELEVENLABS_TRANSLATION_DEFAULT_TARGET: str = os.getenv("ELEVENLABS_TRANSLATION_DEFAULT_TARGET", "en").strip().lower()
    ELEVENLABS_TRANSLATION_SOURCE_LANGS: list[str] = _parse_csv(
        "ELEVENLABS_TRANSLATION_SOURCE_LANGS",
        "hi,mr",
    )
    ELEVENLABS_TRANSLATION_MAX_CHARS: int = int(os.getenv("ELEVENLABS_TRANSLATION_MAX_CHARS", "1100"))
    ELEVENLABS_TRANSLATION_RETRIES: int = int(os.getenv("ELEVENLABS_TRANSLATION_RETRIES", "2"))
    ELEVENLABS_TRANSLATION_TIMEOUT_SECONDS: int = int(os.getenv("ELEVENLABS_TRANSLATION_TIMEOUT_SECONDS", "240"))
    ELEVENLABS_TRANSLATION_POLL_INTERVAL_SECONDS: float = float(
        os.getenv("ELEVENLABS_TRANSLATION_POLL_INTERVAL_SECONDS", "2.0")
    )
    ELEVENLABS_TRANSLATION_DELETE_DUB: bool = _parse_bool("ELEVENLABS_TRANSLATION_DELETE_DUB", "true")
    ELEVENLABS_TRANSLATION_FALLBACK_TO_SOURCE: bool = _parse_bool(
        "ELEVENLABS_TRANSLATION_FALLBACK_TO_SOURCE",
        "true",
    )

    # ── TTS — OpenAI (secondary fallback) ─────────────────────────────
    OPENAI_TTS_API_KEYS: list[str] = _parse_key_list("OPENAI_TTS_API_KEYS")
    OPENAI_TTS_VOICE: str = os.getenv("OPENAI_TTS_VOICE", "alloy")
    OPENAI_TTS_MODEL: str = os.getenv("OPENAI_TTS_MODEL", "tts-1")

    # ── TTS — Edge-TTS (free fallback, no keys needed) ───────────────
    EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "en-US-AriaNeural")
    EDGE_TTS_VOICE_HI: str = os.getenv("EDGE_TTS_VOICE_HI", "hi-IN-SwaraNeural")
    EDGE_TTS_VOICE_MR: str = os.getenv("EDGE_TTS_VOICE_MR", "mr-IN-AarohiNeural")

    # ── LLM — Google Gemini (FREE primary) ────────────────────────────
    # Signup: https://aistudio.google.com/apikey
    # Free tier: gemini-2.5-flash (free with rate limits as of March 2026)
    # Note: gemini-2.0-flash free tier was discontinued — use gemini-2.5-flash
    GOOGLE_GEMINI_API_KEYS: list[str] = _parse_key_list("GOOGLE_GEMINI_API_KEYS")
    GOOGLE_GEMINI_MODEL: str = os.getenv("GOOGLE_GEMINI_MODEL", "gemini-2.5-flash")

    # ── LLM — OpenAI (fallback if you have credits) ──────────────────
    OPENAI_LLM_API_KEYS: list[str] = _parse_key_list("OPENAI_LLM_API_KEYS")
    OPENAI_LLM_MODEL: str = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")

    # ── LLM — Anthropic (fallback) ───────────────────────────────────
    ANTHROPIC_API_KEYS: list[str] = _parse_key_list("ANTHROPIC_API_KEYS")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    # ── TTS provider preference order ─────────────────────────────────
    TTS_PROVIDER_ORDER: list[str] = [
        p.strip().lower()
        for p in os.getenv("TTS_PROVIDER_ORDER", "elevenlabs,openai,edge").split(",")
        if p.strip()
    ]

    # ── LLM provider preference order ─────────────────────────────────
    # Default: Gemini first (free), then OpenAI, then Anthropic
    LLM_PROVIDER_ORDER: list[str] = [
        p.strip().lower()
        for p in os.getenv("LLM_PROVIDER_ORDER", "gemini,openai,anthropic").split(",")
        if p.strip()
    ]

    # ── Legacy Piper TTS (unused, kept for backward compat) ──────────
    PIPER_MODEL_PATH: str = os.getenv("PIPER_MODEL_PATH", "./models/piper/en_US-lessac-medium.onnx")
    PIPER_CONFIG_PATH: str = os.getenv("PIPER_CONFIG_PATH", "./models/piper/en_US-lessac-medium.onnx.json")

    # ── Audio output ──────────────────────────────────────────────────
    AUDIO_OUTPUT_DIR: str = os.getenv("AUDIO_OUTPUT_DIR", "./audio_output")

    # ── Audio generation tuning ───────────────────────────────────────
    AUDIO_GENERATION_TIMEOUT_SECONDS: int = int(os.getenv("AUDIO_GENERATION_TIMEOUT_SECONDS", "1800"))
    AUDIO_GENERATION_MAX_RETRIES: int = int(os.getenv("AUDIO_GENERATION_MAX_RETRIES", "3"))
    TTS_CHUNK_SIZE: int = int(os.getenv("TTS_CHUNK_SIZE", "1500"))  # chars per TTS chunk
    TTS_PARALLEL_CHUNKS: int = int(os.getenv("TTS_PARALLEL_CHUNKS", "5"))  # concurrent chunk requests

    # OCR fallback for scanned/image PDFs
    PDF_OCR_ENABLED: bool = _parse_bool("PDF_OCR_ENABLED", "true")
    PDF_OCR_LANGUAGES: str = os.getenv("PDF_OCR_LANGUAGES", "hin+mar+eng")
    PDF_OCR_DPI: int = int(os.getenv("PDF_OCR_DPI", "300"))
    PDF_OCR_MIN_PAGE_CHARS: int = int(os.getenv("PDF_OCR_MIN_PAGE_CHARS", "20"))

    # ── Supabase HTTP retries ─────────────────────────────────────────
    SUPABASE_REQUEST_MAX_RETRIES: int = int(os.getenv("SUPABASE_REQUEST_MAX_RETRIES", "3"))


settings = Settings()
