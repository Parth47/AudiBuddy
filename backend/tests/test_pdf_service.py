"""Unit tests for PDF service — text extraction, chapter detection, validation."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pdf_service import (
    PDFExtractionError,
    LLMProcessingError,
    clean_text,
    detect_primary_language,
    detect_language_from_chapters,
    detect_chapters_regex,
    _validate_chapters,
    MAX_PDF_SIZE_BYTES,
    MIN_EXTRACTED_TEXT_LENGTH,
)


# ══════════════════════════════════════════════════════════════════════
# TEXT CLEANING
# ══════════════════════════════════════════════════════════════════════

class TestCleanText:
    def test_removes_excessive_newlines(self):
        text = "Hello\n\n\n\n\nWorld"
        result = clean_text(text)
        assert "\n\n\n" not in result
        assert "Hello" in result and "World" in result

    def test_joins_mid_sentence_breaks(self):
        text = "This is a sentence that\ncontinues on the next line."
        result = clean_text(text)
        assert "that continues" in result

    def test_preserves_paragraph_breaks(self):
        text = "Paragraph one.\n\nParagraph two."
        result = clean_text(text)
        assert "\n\n" in result

    def test_removes_page_numbers(self):
        text = "Some text.\n 42 \nMore text."
        result = clean_text(text)
        assert "42" not in result

    def test_strips_whitespace(self):
        text = "  hello   world  "
        result = clean_text(text)
        assert result == "hello world"

    def test_empty_string(self):
        assert clean_text("") == ""
        assert clean_text("   ") == ""

    def test_devanagari_combining_marks_spacing(self):
        text = "कि ताब\nयहां प र शब्द"
        result = clean_text(text)
        # Ensure text remains valid Unicode and does not lose Devanagari marks.
        assert "ि" in result
        assert "यहां" in result


class TestLanguageDetection:
    def test_detect_hindi(self):
        text = "यह एक हिंदी वाक्य है। यह किताब बहुत अच्छी है।"
        assert detect_primary_language(text) in {"hi", "mixed"}

    def test_detect_marathi(self):
        text = "हे मराठी वाक्य आहे. आपण या पुस्तकामध्ये पुढे जाऊ."
        assert detect_primary_language(text) in {"mr", "mixed"}

    def test_detect_language_from_chapters(self):
        chapters = [
            {"title": "अध्याय 1", "text": "हे एक मराठी वाक्य आहे."},
            {"title": "अध्याय 2", "text": "आपण पुढे जाऊ आणि शिकू."},
        ]
        assert detect_language_from_chapters(chapters) in {"mr", "mixed", "hi"}


# ══════════════════════════════════════════════════════════════════════
# REGEX CHAPTER DETECTION
# ══════════════════════════════════════════════════════════════════════

class TestDetectChaptersRegex:
    def test_chapter_numbered(self):
        text = """Chapter 1: The Beginning

Some content for chapter one.

Chapter 2: The Middle

Content for chapter two.

Chapter 3: The End

Content for chapter three."""
        chapters = detect_chapters_regex(text)
        assert len(chapters) >= 2
        assert any("Beginning" in ch["title"] or "1" in ch["title"] for ch in chapters)

    def test_no_chapters_returns_full_text(self):
        text = "Just a regular block of text with no chapter headings at all. " * 10
        chapters = detect_chapters_regex(text)
        assert len(chapters) == 1
        assert chapters[0]["title"] == "Full Text"

    def test_all_caps_titles(self):
        text = """THE BEGINNING OF TIME

Some content here about the beginning.

THE MIDDLE AGES

Content about the middle ages."""
        chapters = detect_chapters_regex(text)
        assert len(chapters) >= 1

    def test_part_headings(self):
        text = """Part I: Foundation

Content of part one.

Part II: Growth

Content of part two."""
        chapters = detect_chapters_regex(text)
        assert len(chapters) >= 2

    def test_empty_chapters_filtered(self):
        text = """Chapter 1: First

Content here.

Chapter 2: Empty
Chapter 3: Also has content

Real content here."""
        chapters = detect_chapters_regex(text)
        # Chapter 2 has no content between it and Chapter 3, so it should be filtered
        for ch in chapters:
            assert ch.get("text", "").strip() != ""


# ══════════════════════════════════════════════════════════════════════
# CHAPTER VALIDATION
# ══════════════════════════════════════════════════════════════════════

class TestValidateChapters:
    def test_valid_chapters_pass(self):
        chapters = [
            {"title": "Ch1", "text": "Some real content here."},
            {"title": "Ch2", "text": "More content."},
        ]
        # Should not raise
        _validate_chapters(chapters)

    def test_all_empty_raises(self):
        chapters = [
            {"title": "Ch1", "text": ""},
            {"title": "Ch2", "text": "   "},
            {"title": "Ch3"},
        ]
        with pytest.raises(LLMProcessingError, match="empty"):
            _validate_chapters(chapters)

    def test_mixed_valid_and_empty(self):
        chapters = [
            {"title": "Ch1", "text": ""},
            {"title": "Ch2", "text": "Has content"},
        ]
        # Should not raise — at least one valid chapter
        _validate_chapters(chapters)


# ══════════════════════════════════════════════════════════════════════
# PDF EXTRACTION (with mocked fitz)
# ══════════════════════════════════════════════════════════════════════

class TestExtractTextFromPdf:
    def test_oversized_pdf_rejected(self):
        """PDFs larger than MAX_PDF_SIZE_BYTES should raise PDFExtractionError."""
        from app.services.pdf_service import extract_text_from_pdf
        huge_bytes = b"x" * (MAX_PDF_SIZE_BYTES + 1)
        with pytest.raises(PDFExtractionError, match="too large"):
            extract_text_from_pdf(huge_bytes)

    def test_empty_pdf_rejected(self):
        from app.services.pdf_service import extract_text_from_pdf
        with pytest.raises(PDFExtractionError, match="empty"):
            extract_text_from_pdf(b"")

    def test_corrupted_pdf_raises(self):
        """Random bytes should fail to open as PDF."""
        from app.services.pdf_service import extract_text_from_pdf
        with pytest.raises(PDFExtractionError, match="corrupted|Failed"):
            extract_text_from_pdf(b"not a real pdf at all")


# ══════════════════════════════════════════════════════════════════════
# PROCESS PDF (integration — mocked LLM + fitz)
# ══════════════════════════════════════════════════════════════════════

class TestProcessPdf:
    @pytest.mark.asyncio
    async def test_fallback_mode_uses_regex(self):
        """When use_fallback=True, LLM is skipped and regex is used."""
        from app.services.pdf_service import process_pdf

        fake_text = "Chapter 1: Intro\n\nSome great content here for the first chapter.\n\nChapter 2: More\n\nMore content in chapter two."

        with patch("app.services.pdf_service.extract_text_from_pdf", return_value=fake_text):
            chapters = await process_pdf(b"fake", use_fallback=True)
            assert len(chapters) >= 1
            assert all(ch.get("text") for ch in chapters)

    @pytest.mark.asyncio
    async def test_llm_failure_raises_llm_error(self):
        """When LLM fails and use_fallback is False, raises LLMProcessingError."""
        from app.services.pdf_service import process_pdf

        fake_text = "A sufficiently long text to pass the minimum length check. " * 10

        with patch("app.services.pdf_service.extract_text_from_pdf", return_value=fake_text):
            with patch("app.services.pdf_service.segment_chapters_with_llm", side_effect=Exception("LLM down")):
                with pytest.raises(LLMProcessingError, match="LLM processing failed"):
                    await process_pdf(b"fake", use_fallback=False)
