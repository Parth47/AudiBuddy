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


class Settings:
    # ── Admin mode ──────────────────────────────────────────────────
    # Set to "true" when running locally. When False, upload/edit/delete
    # endpoints are disabled so the public deployment is read-only.
    ADMIN_MODE: bool = os.getenv("ADMIN_MODE", "false").lower() in ("true", "1", "yes")

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
    ELEVENLABS_MONTHLY_CHAR_LIMIT: int = int(os.getenv("ELEVENLABS_MONTHLY_CHAR_LIMIT", "10000"))

    # ── TTS — OpenAI (secondary fallback) ─────────────────────────────
    OPENAI_TTS_API_KEYS: list[str] = _parse_key_list("OPENAI_TTS_API_KEYS")
    OPENAI_TTS_VOICE: str = os.getenv("OPENAI_TTS_VOICE", "alloy")
    OPENAI_TTS_MODEL: str = os.getenv("OPENAI_TTS_MODEL", "tts-1")

    # ── TTS — Edge-TTS (free fallback, no keys needed) ───────────────
    EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "en-US-AriaNeural")

    # ── LLM — Google Gemini (FREE primary) ────────────────────────────
    # Signup: https://aistudio.google.com/apikey
    # Free tier: 15 RPM, 1M tokens/day for gemini-2.0-flash
    GOOGLE_GEMINI_API_KEYS: list[str] = _parse_key_list("GOOGLE_GEMINI_API_KEYS")
    GOOGLE_GEMINI_MODEL: str = os.getenv("GOOGLE_GEMINI_MODEL", "gemini-2.0-flash")

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

    # ── Supabase HTTP retries ─────────────────────────────────────────
    SUPABASE_REQUEST_MAX_RETRIES: int = int(os.getenv("SUPABASE_REQUEST_MAX_RETRIES", "3"))


settings = Settings()
