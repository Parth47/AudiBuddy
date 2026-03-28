"""Unit tests for TTS service — text splitting, provider cascade logic."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tts_service import split_text_into_chunks


# ══════════════════════════════════════════════════════════════════════
# TEXT SPLITTING
# ══════════════════════════════════════════════════════════════════════

class TestSplitTextIntoChunks:
    def test_short_text_single_chunk(self):
        text = "This is a short sentence."
        chunks = split_text_into_chunks(text, max_chars=1000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_on_sentences(self):
        # Create text with many sentences that exceed max_chars
        sentences = ["This is sentence number %d." % i for i in range(50)]
        text = " ".join(sentences)
        chunks = split_text_into_chunks(text, max_chars=200)
        assert len(chunks) > 1
        # Verify all text is preserved
        reconstructed = " ".join(chunks)
        # Allow minor whitespace differences
        assert len(reconstructed) >= len(text) * 0.95

    def test_respects_max_chars(self):
        sentences = ["This is a fairly long sentence number %d that goes on for a bit." % i for i in range(20)]
        text = " ".join(sentences)
        chunks = split_text_into_chunks(text, max_chars=300)
        for chunk in chunks:
            # Each chunk should be at or near max_chars (may exceed slightly if a sentence is very long)
            assert len(chunk) < 600  # generous upper bound

    def test_empty_text(self):
        chunks = split_text_into_chunks("", max_chars=1000)
        assert len(chunks) == 1
        assert chunks[0] == ""

    def test_single_very_long_sentence(self):
        """A single sentence longer than max_chars should still be returned."""
        text = "A" * 2000 + "."
        chunks = split_text_into_chunks(text, max_chars=500)
        # The single sentence can't be split further, so it may exceed max_chars
        assert len(chunks) >= 1
        total_chars = sum(len(c) for c in chunks)
        assert total_chars >= 2000

    def test_sentence_boundaries_preserved(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = split_text_into_chunks(text, max_chars=40)
        # Each chunk should end with a sentence-ending character (period)
        for chunk in chunks:
            stripped = chunk.strip()
            if stripped:
                assert stripped[-1] in ".!?"

    def test_exclamation_and_question_marks(self):
        text = "What is this? I don't know! But let me think. Maybe it works?"
        chunks = split_text_into_chunks(text, max_chars=30)
        assert len(chunks) > 1

    def test_devanagari_sentence_boundaries(self):
        text = "यह पहला वाक्य है। यह दूसरा वाक्य है। यह तीसरा वाक्य है।"
        chunks = split_text_into_chunks(text, max_chars=35)
        assert len(chunks) > 1


# ══════════════════════════════════════════════════════════════════════
# PROVIDER CASCADE (mocked)
# ══════════════════════════════════════════════════════════════════════

class TestProviderCascade:
    @pytest.mark.asyncio
    async def test_fallback_to_next_provider_on_failure(self):
        """When first provider fails, cascade should try the next."""
        from app.services.tts_service import text_to_mp3_bytes

        # Mock _get_provider_order to return fake providers
        fake_audio = b"\xff\xfb\x90\x00" + b"\x00" * 512  # Fake MP3 header + padding

        async def failing_provider(text):
            raise RuntimeError("Provider 1 down")

        async def working_provider(text):
            return fake_audio

        with patch("app.services.tts_service._get_provider_order", return_value=[
            ("failing", failing_provider),
            ("working", working_provider),
        ]):
            result = await text_to_mp3_bytes("Hello world")
            assert len(result) > 256  # > _MIN_VALID_MP3_BYTES

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self):
        """When all providers fail, should raise RuntimeError."""
        from app.services.tts_service import text_to_mp3_bytes

        async def failing_provider(text):
            raise RuntimeError("Provider down")

        with patch("app.services.tts_service._get_provider_order", return_value=[
            ("p1", failing_provider),
            ("p2", failing_provider),
        ]):
            with pytest.raises(RuntimeError, match="All TTS providers failed"):
                await text_to_mp3_bytes("Hello")

    @pytest.mark.asyncio
    async def test_elevenlabs_exhaustion_skips_retries(self):
        """When ElevenLabs reports 'exhausted', should skip retries and fall to next."""
        from app.services.tts_service import text_to_mp3_bytes
        fake_audio = b"\xff\xfb\x90\x00" + b"\x00" * 512

        call_count = 0

        async def exhausted_elevenlabs(text):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("All keys exhausted for this month")

        async def working_edge(text):
            return fake_audio

        with patch("app.services.tts_service._get_provider_order", return_value=[
            ("elevenlabs", exhausted_elevenlabs),
            ("edge", working_edge),
        ]):
            result = await text_to_mp3_bytes("Hello")
            assert len(result) > 256
            # Should have called elevenlabs only once (no retries for "exhausted")
            assert call_count == 1


# ══════════════════════════════════════════════════════════════════════
# CHAPTER AUDIO GENERATION (mocked)
# ══════════════════════════════════════════════════════════════════════

class TestGenerateChapterAudio:
    @pytest.mark.asyncio
    async def test_single_chunk_chapter(self):
        """Short text that fits in one chunk."""
        from app.services.tts_service import generate_chapter_audio
        fake_audio = b"\xff\xfb\x90\x00" + b"\x00" * 512

        with patch("app.services.tts_service.text_to_mp3_bytes", new_callable=AsyncMock, return_value=fake_audio):
            result = await generate_chapter_audio("Short text.")
            assert len(result) > 256

    @pytest.mark.asyncio
    async def test_empty_text_raises(self):
        from app.services.tts_service import generate_chapter_audio
        with pytest.raises(ValueError, match="No text"):
            await generate_chapter_audio("")

    @pytest.mark.asyncio
    async def test_multi_chunk_concatenation(self):
        """Long text should be split and concatenated."""
        from app.services.tts_service import generate_chapter_audio
        chunk1 = b"\xff\xfb\x90\x00" + b"\x01" * 512
        chunk2 = b"\xff\xfb\x90\x00" + b"\x02" * 512

        call_idx = 0

        async def mock_tts(text):
            nonlocal call_idx
            call_idx += 1
            return chunk1 if call_idx % 2 else chunk2

        long_text = "This is a long sentence. " * 200  # ~5000 chars

        with patch("app.services.tts_service.text_to_mp3_bytes", side_effect=mock_tts):
            result = await generate_chapter_audio(long_text)
            assert len(result) > 512  # At least 2 chunks concatenated

    @pytest.mark.asyncio
    async def test_progress_callback(self):
        """on_chunk_complete should be called for each chunk."""
        from app.services.tts_service import generate_chapter_audio
        fake_audio = b"\xff\xfb\x90\x00" + b"\x00" * 512
        progress_calls = []

        def on_progress(completed, total):
            progress_calls.append((completed, total))

        with patch("app.services.tts_service.text_to_mp3_bytes", new_callable=AsyncMock, return_value=fake_audio):
            await generate_chapter_audio("Short.", on_chunk_complete=on_progress)
            assert len(progress_calls) == 1
            assert progress_calls[0] == (1, 1)
