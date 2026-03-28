"""Unit tests for translation service logic and fallback behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.translation_service import (
    maybe_translate_for_tts,
    normalize_translation_target,
    resolve_translation_target,
)


class TestTranslationTargetResolution:
    def test_normalize_translation_target(self):
        assert normalize_translation_target("english") == "en"
        assert normalize_translation_target("hindi") == "hi"
        assert normalize_translation_target("marathi") == "mr"
        assert normalize_translation_target("none") == "none"
        assert normalize_translation_target("weird") == "auto"

    def test_auto_translates_hindi_to_default_target(self):
        assert resolve_translation_target("hi", "auto") == "en"

    def test_auto_skips_english(self):
        assert resolve_translation_target("en", "auto") is None

    def test_explicit_none_skips_translation(self):
        assert resolve_translation_target("mr", "none") is None

    def test_explicit_same_language_skips_translation(self):
        assert resolve_translation_target("hi", "hi") is None


class TestMaybeTranslateForTts:
    @pytest.mark.asyncio
    async def test_returns_source_text_when_translation_not_needed(self):
        result = await maybe_translate_for_tts(
            text="Plain English text.",
            source_language="en",
            requested_target="auto",
        )
        assert result.applied is False
        assert result.text == "Plain English text."
        assert result.tts_language == "en"

    @pytest.mark.asyncio
    async def test_applies_translation_when_available(self):
        fake_keys = SimpleNamespace(has_keys=True)
        with patch("app.services.translation_service._translation_keys", fake_keys):
            with patch(
                "app.services.translation_service.translate_text_via_elevenlabs",
                new=AsyncMock(return_value="Translated text in English."),
            ):
                result = await maybe_translate_for_tts(
                    text="यह हिंदी वाक्य है।",
                    source_language="hi",
                    requested_target="auto",
                )

        assert result.applied is True
        assert result.text == "Translated text in English."
        assert result.tts_language == "en"
        assert result.target_language == "en"

    @pytest.mark.asyncio
    async def test_falls_back_to_source_when_translation_errors(self):
        fake_keys = SimpleNamespace(has_keys=True)
        with patch("app.services.translation_service._translation_keys", fake_keys):
            with patch(
                "app.services.translation_service.translate_text_via_elevenlabs",
                new=AsyncMock(side_effect=RuntimeError("translation failed")),
            ):
                result = await maybe_translate_for_tts(
                    text="हे मराठी वाक्य आहे.",
                    source_language="mr",
                    requested_target="en",
                )

        assert result.applied is False
        assert result.text == "हे मराठी वाक्य आहे."
        assert result.tts_language == "mr"
