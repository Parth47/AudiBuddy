"""PDF processing service with multilingual extraction and OCR fallback.

Pipeline:
1. Extract text from PDF with PyMuPDF
2. Run OCR per page when extraction is missing or corrupted
3. Normalize Unicode and clean text for narration
4. Detect chapters (LLM first, regex fallback)
"""

from __future__ import annotations

import logging
import re
import unicodedata

import fitz  # PyMuPDF

from app.core.config import settings
from app.services.llm_chapter_service import segment_chapters_with_llm

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency path
    pytesseract = None
    Image = None

try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException

    DetectorFactory.seed = 0
except Exception:  # pragma: no cover - optional dependency path
    detect_langs = None
    LangDetectException = Exception

# Maximum PDF file size: 200 MB
MAX_PDF_SIZE_BYTES = 200 * 1024 * 1024
# Minimum meaningful text length after extraction
MIN_EXTRACTED_TEXT_LENGTH = 50

_DEVANAGARI_CHAR_RE = re.compile(r"[\u0900-\u097F]")
_DEVANAGARI_WORD_RE = re.compile(r"[\u0900-\u097F]+")
_DEVANAGARI_COMBINING_RE = re.compile(r"[\u093A-\u094D\u0951-\u0957\u0962-\u0963]")
_PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u2060\ufeff]")
_ROMAN_NUMERAL_RE = r"[IVXivx]+"
_NUMBER_TOKEN_RE = r"[0-9०-९]+"

_MARATHI_HINTS = {
    "आहे",
    "आहेत",
    "आणि",
    "मध्ये",
    "होते",
    "होती",
    "साठी",
    "नसते",
    "त्यांनी",
    "त्यांच्या",
}
_HINDI_HINTS = {
    "है",
    "हैं",
    "और",
    "लेकिन",
    "नहीं",
    "किया",
    "किये",
    "करते",
    "होता",
    "होती",
    "क्योंकि",
}


class PDFExtractionError(Exception):
    """Raised when PDF text extraction fails or produces no usable text."""


class LLMProcessingError(Exception):
    """Raised when LLM processing fails so the caller can offer a fallback."""


def normalize_language_code(language: str | None) -> str:
    """Normalize language labels used across frontend/backend."""
    if not language:
        return "auto"
    value = language.strip().lower()
    aliases = {
        "auto": "auto",
        "automatic": "auto",
        "en": "en",
        "english": "en",
        "hi": "hi",
        "hindi": "hi",
        "mr": "mr",
        "marathi": "mr",
        "mixed": "mixed",
    }
    return aliases.get(value, "auto")


def normalize_unicode_text(text: str) -> str:
    """Normalize Unicode while preserving Devanagari readability."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")  # non-breaking space
    text = text.replace("\u2007", " ").replace("\u202f", " ")
    text = text.replace("\u00ad", "")  # soft hyphen
    text = _ZERO_WIDTH_RE.sub("", text)
    return unicodedata.normalize("NFC", text)


def _langdetect_guess(text: str) -> tuple[str, float] | None:
    """Best-effort language guess using langdetect when available."""
    if detect_langs is None:
        return None

    sample = " ".join(text.split())
    if len(sample) > 5000:
        sample = sample[:5000]

    try:
        guesses = detect_langs(sample)
    except LangDetectException:
        return None
    except Exception:
        return None

    for guess in guesses:
        code = (getattr(guess, "lang", "") or "").lower()
        prob = float(getattr(guess, "prob", 0.0) or 0.0)
        if code in {"en", "hi", "mr"}:
            return code, prob
    return None


def detect_primary_language(text: str) -> str:
    """Detect primary language from extracted text.

    Returns one of: en, hi, mr, mixed
    """
    cleaned = normalize_unicode_text(text)
    if not cleaned.strip():
        return "en"

    devanagari_count = len(_DEVANAGARI_CHAR_RE.findall(cleaned))
    latin_count = len(re.findall(r"[A-Za-z]", cleaned))
    total_script_chars = devanagari_count + latin_count

    langdetect_guess = _langdetect_guess(cleaned)

    if devanagari_count == 0:
        if langdetect_guess and langdetect_guess[0] in {"hi", "mr"} and langdetect_guess[1] >= 0.90:
            return langdetect_guess[0]
        return "en"
    if devanagari_count < 8 and latin_count > devanagari_count * 2:
        return "en"

    mixed_script = False
    if total_script_chars > 0:
        devanagari_ratio = devanagari_count / total_script_chars
        if devanagari_ratio < 0.35:
            return "mixed"
        if 0.35 <= devanagari_ratio <= 0.85 and latin_count > 20:
            mixed_script = True

    words = [w for w in _DEVANAGARI_WORD_RE.findall(cleaned) if len(w) > 1]
    if not words:
        if langdetect_guess and langdetect_guess[0] in {"hi", "mr"}:
            return langdetect_guess[0]
        return "hi"

    marathi_score = sum(1 for w in words if w in _MARATHI_HINTS)
    hindi_score = sum(1 for w in words if w in _HINDI_HINTS)

    if marathi_score == 0 and hindi_score == 0:
        if langdetect_guess and langdetect_guess[0] in {"hi", "mr"} and langdetect_guess[1] >= 0.75:
            detected = langdetect_guess[0]
        else:
            detected = "hi"
    else:
        total_score = marathi_score + hindi_score
        if total_score > 0 and abs(marathi_score - hindi_score) <= max(1, total_score // 4):
            detected = "mr" if marathi_score >= hindi_score else "hi"
        else:
            detected = "mr" if marathi_score > hindi_score else "hi"

    if langdetect_guess and langdetect_guess[0] in {"hi", "mr"} and langdetect_guess[1] >= 0.88:
        detected = langdetect_guess[0]

    if mixed_script and latin_count > devanagari_count * 0.4:
        return "mixed"
    if latin_count > devanagari_count * 1.1:
        return "mixed"

    return detected


def detect_language_from_chapters(chapters: list[dict]) -> str:
    """Detect language from chapter texts."""
    if not chapters:
        return "en"
    sample_text = "\n".join(
        (chapter.get("text") or "")[:3000]
        for chapter in chapters[:6]
    )
    return detect_primary_language(sample_text)


def _ocr_is_available() -> bool:
    return bool(settings.PDF_OCR_ENABLED and pytesseract and Image)


def _extract_page_text_ocr(page: fitz.Page, page_number: int) -> str:
    """Run OCR on a single page."""
    if not _ocr_is_available():
        return ""

    dpi = max(150, int(settings.PDF_OCR_DPI))
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)

    image = None
    try:
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        ocr_text = pytesseract.image_to_string(
            image,
            lang=settings.PDF_OCR_LANGUAGES,
            config="--oem 1 --psm 6",
        )
        return normalize_unicode_text(ocr_text)
    except Exception as exc:  # pragma: no cover - depends on external tesseract
        logger.warning("OCR failed on page %d: %s", page_number, exc)
        return ""
    finally:
        if image is not None:
            image.close()


def _page_looks_corrupted(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True

    min_chars = max(5, int(settings.PDF_OCR_MIN_PAGE_CHARS))
    if len(stripped) < min_chars:
        return True

    replacement_count = stripped.count("\ufffd")
    if replacement_count and replacement_count / max(1, len(stripped)) > 0.01:
        return True

    private_use_count = len(_PRIVATE_USE_RE.findall(stripped))
    if private_use_count and private_use_count / max(1, len(stripped)) > 0.02:
        return True

    dev_chars = len(_DEVANAGARI_CHAR_RE.findall(stripped))
    dev_marks = len(_DEVANAGARI_COMBINING_RE.findall(stripped))
    if dev_chars > 0 and dev_marks > dev_chars:
        return True

    return False


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract all text from PDF with OCR fallback for difficult pages."""
    if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
        raise PDFExtractionError(
            f"PDF is too large ({len(pdf_bytes) / (1024 * 1024):.1f} MB). "
            f"Maximum supported size is {MAX_PDF_SIZE_BYTES / (1024 * 1024):.0f} MB."
        )

    if len(pdf_bytes) == 0:
        raise PDFExtractionError("PDF file is empty (0 bytes).")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PDFExtractionError(
            f"Failed to open PDF. It may be corrupted, encrypted, or invalid. Details: {exc}"
        ) from exc

    try:
        if doc.is_encrypted:
            raise PDFExtractionError("PDF is password-protected. Please upload an unencrypted PDF.")

        page_count = len(doc)
        if page_count == 0:
            raise PDFExtractionError("PDF has 0 pages.")

        logger.info("Extracting text from %d-page PDF (%.1f MB)", page_count, len(pdf_bytes) / (1024 * 1024))

        page_texts: list[str] = []
        empty_pages = 0
        ocr_pages = 0

        for page_num in range(page_count):
            page = doc[page_num]
            text = ""
            try:
                text = normalize_unicode_text(page.get_text("text", sort=True))
            except Exception as exc:
                logger.warning("Text extraction failed for page %d: %s", page_num + 1, exc)

            if _ocr_is_available() and _page_looks_corrupted(text):
                ocr_text = _extract_page_text_ocr(page, page_num + 1)
                if ocr_text.strip():
                    text = ocr_text
                    ocr_pages += 1

            if text and text.strip():
                page_texts.append(text.strip())
            else:
                page_texts.append("")
                empty_pages += 1

        full_text = "\n\n".join(chunk for chunk in page_texts if chunk)

        if len(full_text.strip()) < MIN_EXTRACTED_TEXT_LENGTH:
            if empty_pages == page_count:
                if settings.PDF_OCR_ENABLED and not _ocr_is_available():
                    raise PDFExtractionError(
                        "No text could be extracted. OCR fallback is enabled but unavailable. "
                        "Install Tesseract OCR and Python deps (pytesseract, Pillow), and ensure "
                        f"language packs are installed: {settings.PDF_OCR_LANGUAGES}."
                    )
                raise PDFExtractionError(
                    "No text could be extracted from this PDF. It may be image-only or use unsupported fonts."
                )
            raise PDFExtractionError(
                f"Extracted text is too short ({len(full_text.strip())} chars). "
                "The PDF may be mostly images or low-quality scans."
            )

        logger.info(
            "Text extracted: %d chars, empty_pages=%d, ocr_pages=%d/%d",
            len(full_text),
            empty_pages,
            ocr_pages,
            page_count,
        )
        return full_text
    finally:
        doc.close()


def clean_text(text: str) -> str:
    """Clean and normalize extracted text for English + Devanagari scripts."""
    text = normalize_unicode_text(text)

    # Fix artificial spaces before/after Devanagari combining marks.
    text = re.sub(r"([\u0900-\u097F])\s+([\u093A-\u094D\u0951-\u0957\u0962-\u0963])", r"\1\2", text)
    text = re.sub(r"([\u093A-\u094D\u0951-\u0957\u0962-\u0963])\s+([\u0900-\u097F])", r"\1\2", text)

    # Remove standalone page numbers (ASCII + Devanagari digits) before reflowing lines.
    text = re.sub(r"\n\s*[0-9०-९]{1,4}\s*\n", "\n", text)

    # Remove spaces before Devanagari sentence punctuation.
    text = re.sub(r"\s+([।॥])", r"\1", text)

    # Rejoin words split with hard line breaks.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Join wrapped lines when the previous line does not end a sentence.
    text = re.sub(
        r"(?<![.!?:;।॥\n])\n(?=[A-Za-z0-9\u0900-\u097F\"'(\[])",
        " ",
        text,
    )

    # Collapse repeated blank lines to paragraph boundaries.
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Normalize spaces/tabs.
    text = re.sub(r"[ \t]+", " ", text)

    # Trim each line while preserving paragraphs.
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


CHAPTER_PATTERNS = [
    # English chapter/part styles
    r"(?i)^chapter\s+(?:\d+|[ivxlc]+)[.:\s-]*(.*)$",
    r"(?i)^part\s+(?:\d+|[ivxlc]+)[.:\s-]*(.*)$",
    # Hindi / Marathi chapter styles
    rf"^अध्याय\s*(?:{_NUMBER_TOKEN_RE}|{_ROMAN_NUMERAL_RE})?[.:\s-]*(.*)$",
    rf"^प्रकरण\s*(?:{_NUMBER_TOKEN_RE}|{_ROMAN_NUMERAL_RE})?[.:\s-]*(.*)$",
    rf"^भाग\s*(?:{_NUMBER_TOKEN_RE}|{_ROMAN_NUMERAL_RE})?[.:\s-]*(.*)$",
    # Numbered heading styles (supports Devanagari digits too)
    rf"^(?:{_NUMBER_TOKEN_RE}|{_ROMAN_NUMERAL_RE})[.:\-]\s+(.*)$",
    # All-caps heading (English fallback)
    r"^([A-Z][A-Z\s]{8,})$",
]


def detect_chapters_regex(text: str) -> list[dict]:
    """Detect chapter boundaries using regex patterns."""
    lines = text.split("\n")
    chapter_breaks: list[tuple[int, str]] = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) > 120:
            continue

        for pattern in CHAPTER_PATTERNS:
            match = re.match(pattern, stripped)
            if not match:
                continue

            # Avoid false positive numeric headings inside paragraphs.
            if pattern.startswith("^(?:") and idx > 0 and lines[idx - 1].strip():
                continue

            groups = [g.strip() for g in match.groups() if g and g.strip()]
            title = groups[0] if groups else stripped
            chapter_breaks.append((idx, title))
            break

    if not chapter_breaks:
        return [{"title": "Full Text", "text": text}]

    chapters: list[dict] = []
    for i, (line_idx, title) in enumerate(chapter_breaks):
        next_line_idx = chapter_breaks[i + 1][0] if i + 1 < len(chapter_breaks) else len(lines)
        chapter_text = "\n".join(lines[line_idx + 1:next_line_idx]).strip()
        if chapter_text:
            chapters.append({"title": title, "text": chapter_text})

    if not chapters:
        return [{"title": "Full Text", "text": text}]
    return chapters


async def process_pdf(pdf_bytes: bytes, use_fallback: bool = False) -> list[dict]:
    """Full pipeline: extract -> clean -> chapter detection."""
    raw_text = extract_text_from_pdf(pdf_bytes)
    cleaned = clean_text(raw_text)

    logger.info("PDF text extracted and cleaned: %d characters", len(cleaned))
    if len(cleaned.strip()) < MIN_EXTRACTED_TEXT_LENGTH:
        raise PDFExtractionError(
            f"Cleaned text is too short ({len(cleaned.strip())} characters) to process into chapters."
        )

    if use_fallback:
        logger.info("Using regex chapter detection (fallback requested)")
        chapters = detect_chapters_regex(cleaned)
        _validate_chapters(chapters)
        return chapters

    try:
        llm_chapters = await segment_chapters_with_llm(cleaned)
        if llm_chapters:
            _validate_chapters(llm_chapters)
            logger.info("Using LLM chapter segmentation: %d chapters", len(llm_chapters))
            return llm_chapters
        raise LLMProcessingError("LLM returned no chapters")
    except LLMProcessingError:
        raise
    except Exception as exc:
        logger.warning("LLM chapter segmentation failed: %s", exc)
        raise LLMProcessingError(f"LLM processing failed: {exc}") from exc


def _validate_chapters(chapters: list[dict]) -> None:
    """Ensure chapters have non-empty text content."""
    valid = [ch for ch in chapters if (ch.get("text") or "").strip()]
    if not valid:
        raise LLMProcessingError("All generated chapters are empty. No usable content.")


def process_pdf_sync(pdf_bytes: bytes) -> list[dict]:
    """Synchronous fallback pipeline (regex chapter detection)."""
    raw_text = extract_text_from_pdf(pdf_bytes)
    cleaned = clean_text(raw_text)
    return detect_chapters_regex(cleaned)
