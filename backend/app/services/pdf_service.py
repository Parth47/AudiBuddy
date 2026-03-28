"""PDF processing service — extract text, detect chapters, clean content.

Chapter detection now supports two modes:
  1. LLM-based (primary) — uses OpenAI/Anthropic to intelligently segment content
     and remove irrelevant sections (TOC, copyright, acknowledgements, etc.)
  2. Regex-based (fallback) — pattern matching for chapter headings

The process_pdf() function tries LLM first and falls back to regex automatically.
"""

import re
import logging
import fitz  # PyMuPDF

from app.services.llm_chapter_service import segment_chapters_with_llm

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF file."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()
    return full_text


def clean_text(text: str) -> str:
    """Clean and normalize extracted text."""
    # Replace multiple newlines with double newline (paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Replace single newlines that break mid-sentence with space
    text = re.sub(r"(?<![.!?:;\n])\n(?=[a-z])", " ", text)
    # Remove page numbers (standalone numbers on a line)
    text = re.sub(r"\n\s*\d+\s*\n", "\n", text)
    # Remove excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)
    # Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Remove empty lines that are more than 2 in a row
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Regex-based chapter detection (fallback) ─────────────────────────

# Patterns that typically indicate a chapter heading
CHAPTER_PATTERNS = [
    # "Chapter 1", "Chapter One", "CHAPTER 1"
    r"(?i)^chapter\s+[\divxlc]+[.:\s]*(.*)",
    r"(?i)^chapter\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)[.:\s]*(.*)",
    # "Part 1", "PART ONE"
    r"(?i)^part\s+[\divxlc]+[.:\s]*(.*)",
    # "1.", "1:", "I.", "II." at start of line (with optional title after)
    r"^(\d{1,3})[.:]\s+(.*)",
    # ALL CAPS lines that look like titles (at least 3 words)
    r"^([A-Z][A-Z\s]{8,})$",
]


def detect_chapters_regex(text: str) -> list[dict]:
    """Detect chapter boundaries using regex patterns (fallback method).

    Returns a list of dicts: [{"title": "...", "text": "..."}, ...]
    """
    lines = text.split("\n")
    chapter_breaks = []  # list of (line_index, title)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        for pattern in CHAPTER_PATTERNS:
            match = re.match(pattern, stripped)
            if match:
                # Avoid false positives: chapter headings are usually short
                if len(stripped) > 100:
                    continue
                # Avoid matching numbers in the middle of paragraphs
                if i > 0 and lines[i - 1].strip() != "" and pattern == r"^(\d{1,3})[.:]\s+(.*)":
                    continue
                title = match.group(1) if match.groups() else stripped
                title = title.strip() or stripped
                chapter_breaks.append((i, title))
                break

    # If no chapters detected, treat the entire text as one chapter
    if len(chapter_breaks) == 0:
        return [{"title": "Full Text", "text": text}]

    # Build chapter list from breaks
    chapters = []
    for idx, (line_idx, title) in enumerate(chapter_breaks):
        if idx + 1 < len(chapter_breaks):
            next_line_idx = chapter_breaks[idx + 1][0]
            chapter_text = "\n".join(lines[line_idx + 1: next_line_idx])
        else:
            chapter_text = "\n".join(lines[line_idx + 1:])

        chapter_text = chapter_text.strip()
        if chapter_text:  # skip empty chapters
            chapters.append({"title": title, "text": chapter_text})

    # If we found breaks but all chapters ended up empty, return whole text
    if not chapters:
        return [{"title": "Full Text", "text": text}]

    return chapters


# ── Main pipeline ────────────────────────────────────────────────────

class LLMProcessingError(Exception):
    """Raised when LLM processing fails so the caller can offer a fallback."""
    pass


async def process_pdf(pdf_bytes: bytes, use_fallback: bool = False) -> list[dict]:
    """Full pipeline: extract → clean → detect chapters (LLM with regex fallback).

    Returns list of chapter dicts with title and text.

    If use_fallback is True, skips LLM and uses regex directly.
    If LLM fails and use_fallback is False, raises LLMProcessingError
    so the caller can present a fallback option to the user.
    """
    raw_text = extract_text_from_pdf(pdf_bytes)
    cleaned = clean_text(raw_text)

    if use_fallback:
        logger.info("Using regex-based chapter detection (fallback requested by user)")
        chapters = detect_chapters_regex(cleaned)
        return chapters

    # Try LLM-based segmentation first — send entire text
    try:
        llm_chapters = await segment_chapters_with_llm(cleaned)
        if llm_chapters and len(llm_chapters) > 0:
            logger.info(
                "Using LLM chapter segmentation: %d chapters detected", len(llm_chapters)
            )
            return llm_chapters
        else:
            raise LLMProcessingError("LLM returned no chapters")
    except LLMProcessingError:
        raise
    except Exception as exc:
        logger.warning("LLM chapter segmentation failed: %s", exc)
        raise LLMProcessingError(f"LLM processing failed: {exc}") from exc


def process_pdf_sync(pdf_bytes: bytes) -> list[dict]:
    """Synchronous fallback — regex only. Used when async is not available."""
    raw_text = extract_text_from_pdf(pdf_bytes)
    cleaned = clean_text(raw_text)
    return detect_chapters_regex(cleaned)
