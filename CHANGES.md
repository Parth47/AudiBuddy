# AudiBuddy — Hardening & UI/UX Changes Summary

## Overview

This document summarizes all changes made across 8 tasks covering pipeline hardening, API resilience, UI/UX improvements, and test coverage for the AudiBuddy PDF-to-audiobook application.

---

## Task 1: Harden PDF Parsing

**Files modified:** `backend/app/services/pdf_service.py`

- Added `PDFExtractionError` exception class for clear error categorization
- Added file size validation (200 MB max via `MAX_PDF_SIZE_BYTES`)
- Added empty file detection (0-byte PDFs rejected immediately)
- Added encrypted/password-protected PDF detection via `doc.is_encrypted`
- Rewrote `extract_text_from_pdf()` with page-by-page extraction and per-page error handling — a single corrupted page no longer crashes the entire extraction
- Added minimum text length validation (`MIN_EXTRACTED_TEXT_LENGTH = 50`) to catch image-only/scan PDFs
- Added `_validate_chapters()` to ensure generated chapters contain non-empty text
- Memory-efficient: uses list accumulation + join instead of string concatenation

## Task 2: Strengthen LLM Chapter Generation

**Files modified:** `backend/app/services/llm_chapter_service.py`, `backend/app/api/routes/books.py`

- Added `LLMQuotaExhaustedError` with `provider` and `status_code` fields for structured error handling
- Added truncation warnings for all 3 LLM providers when text exceeds safe limits (Gemini >900k chars, OpenAI >300k, Anthropic >400k)
- `segment_chapters_with_llm()` now tracks quota errors separately and raises `LLMQuotaExhaustedError` when most failures are quota-related (enabling frontend to offer key entry)
- Books route now catches `LLMQuotaExhaustedError` and returns structured 422 with `error: "llm_quota_exhausted"` and `can_provide_new_key: true`
- Added `PDFExtractionError` handler returning 422 with `error: "pdf_extraction_failed"`

## Task 3: API Limit Handling — New Key Entry + Fallback

**Files modified:** `backend/app/services/api_key_manager.py`, `backend/app/services/tts_service.py`, `backend/app/services/llm_chapter_service.py`, `backend/app/api/routes/audio.py`, `frontend/src/lib/api.ts`, `frontend/src/app/upload/page.tsx`

**Backend:**
- Added `add_key()` method to `APIKeyManager` for runtime key injection (deduplication, validation)
- Added `add_tts_key()` in tts_service and `add_llm_key()` in llm_chapter_service
- New endpoint `POST /api/audio/add-api-key` with .env file persistence via `_persist_key_to_env()`
- Supports all 5 providers: gemini, openai, anthropic, elevenlabs, openai-tts
- Admin-only (requires `ADMIN_MODE=true`)

**Frontend:**
- Added `UploadQuotaError` class in api.ts for structured quota error handling
- Added `addApiKey()` API function
- Upload page now has a `quota_exhausted` step with two clear options:
  - **Option A:** Enter a new API key (masked input) → "Add Key & Retry" button
  - **Option B:** "Use Fallback Mode" button (regex-based chapter detection, no LLM needed)
- Keys are persisted to .env by default

## Task 4: Enforce TTS/Chapter Dependency

**Files modified:** `backend/app/services/audio_generation.py`, `backend/app/api/routes/audio.py`

- Added hard pipeline gate in `start_audio_generation()`: rejects requests if book `status != 'ready'` or `total_chapters == 0`
- The `/audio/start/{book_id}` endpoint now returns 400 with clear error messages when the gate blocks
- This prevents audio generation from ever running on unprocessed books

## Task 5: Fix Light Mode Card Colors & WCAG Contrast

**Files modified:** `frontend/src/app/globals.css`, `frontend/src/app/library/page.tsx`

**Problem:** Light mode cards appeared too gray/washed out due to low alpha values on translucent card backgrounds.

**CSS variable changes (light mode only):**
- `--card` alpha: 0.82 → 0.94 (cards are now nearly opaque, clean white appearance)
- `--card-foreground` lightness: 0.19 → 0.145 (stronger text contrast)
- `--foreground` lightness: 0.19 → 0.145
- `--popover` alpha: 0.88 → 0.96
- `--muted-foreground` lightness: 0.41 → 0.38 (better WCAG AA contrast on light backgrounds)
- `--border` alpha: 0.84 → 0.92 (crisper borders)
- `--input` alpha: 0.92 → 0.95
- `--secondary-foreground` lightness: 0.23 → 0.18
- `--accent-foreground` lightness: 0.20 → 0.16

**Component class changes:**
- `.glass-nav`: bg-card/75 → bg-card/85, border-border/70 → border-border/80
- `.glass-panel`: bg-card/70 → bg-card/85
- `.surface-card`: bg-card/70 → bg-card/88
- Library page icon: bg-card/70 → bg-card/85
- Library genre badge: bg-card/50 → bg-card/70

**Dark mode:** Unchanged (already had good contrast).

## Task 6: Fix Mobile Click-Away Behavior

**Files modified:** `frontend/src/components/layout/navbar.tsx`

- Added invisible full-screen backdrop overlay behind mobile menu that closes it on tap/click
- Added Escape key handler to close mobile menu
- Added `closeMobile` callback used by all nav links and the backdrop
- All other overlays (shadcn Dialog, DropdownMenu) already handle click-outside via Base UI — verified no other components needed changes

## Task 7: API Key Documentation

Completed during analysis phase. The app requires:
- **Google Gemini API keys** (free tier, primary LLM for chapter segmentation)
- **ElevenLabs API keys** (optional, premium TTS with 10k chars/month free tier)
- **OpenAI API keys** (optional, fallback LLM and TTS)
- **Anthropic API keys** (optional, fallback LLM)
- **Supabase URL + Key** (required, database and file storage)

All keys are configured in `backend/.env`. The new runtime key management endpoint allows adding keys without restarting the server.

## Task 8: Unit & Integration Tests

**Files created:**
- `backend/tests/conftest.py` — shared fixtures, fake settings, mock database
- `backend/tests/test_api_key_manager.py` — 13 tests covering key rotation, character budgets, add_key, deduplication, month reset, stats
- `backend/tests/test_pdf_service.py` — tests for text cleaning, regex chapter detection, chapter validation, PDF extraction guards, process_pdf integration
- `backend/tests/test_tts_service.py` — tests for text splitting, provider cascade fallback, ElevenLabs exhaustion behavior, chapter audio generation, progress callbacks
- `backend/tests/test_audio_routes.py` — integration tests for pipeline gate (rejects unready books, zero chapters, nonexistent books), .env persistence logic, provider map completeness, _fmt_chars helper

**Test execution:** All 13 standalone test groups pass. Full pytest suite requires project dependencies (run with `cd backend && python -m pytest tests/` in the project's virtual environment).

---

## Modified Files Summary

| File | Tasks |
|------|-------|
| `backend/app/services/pdf_service.py` | 1, 2 |
| `backend/app/services/llm_chapter_service.py` | 2, 3 |
| `backend/app/services/api_key_manager.py` | 3 |
| `backend/app/services/tts_service.py` | 3 |
| `backend/app/services/audio_generation.py` | 4 |
| `backend/app/api/routes/audio.py` | 3, 4 |
| `backend/app/api/routes/books.py` | 1, 2 |
| `frontend/src/lib/api.ts` | 3 |
| `frontend/src/app/upload/page.tsx` | 3 |
| `frontend/src/app/globals.css` | 5 |
| `frontend/src/app/library/page.tsx` | 5 |
| `frontend/src/components/layout/navbar.tsx` | 6 |
| `backend/tests/conftest.py` | 8 (new) |
| `backend/tests/test_api_key_manager.py` | 8 (new) |
| `backend/tests/test_pdf_service.py` | 8 (new) |
| `backend/tests/test_tts_service.py` | 8 (new) |
| `backend/tests/test_audio_routes.py` | 8 (new) |

## Running the Tests

```bash
cd backend
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

## Assumptions

- API keys are already configured in `backend/.env`
- The app runs with `ADMIN_MODE=true` for upload and audio generation features
- ElevenLabs free tier limit is 10,000 chars/month per key (configurable via `ELEVENLABS_MONTHLY_CHAR_LIMIT`)
- Dark mode theme was already well-calibrated and did not need changes
- Shadcn UI components (Dialog, DropdownMenu) already handle click-outside behavior correctly
