/**
 * API client for communicating with the FastAPI backend.
 *
 * Production-optimized: shorter timeouts, proper abort handling,
 * and no unnecessary wrapper overhead.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Default timeout for API calls (10s is plenty for DB queries; audio gen uses its own)
const DEFAULT_TIMEOUT_MS = 10_000;

async function fetchAPI<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      signal: options?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        ...options?.headers,
      },
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "API request failed");
    }
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

// --- Types ---

export interface Book {
  id: string;
  title: string;
  author: string;
  description: string | null;
  cover_image_url: string | null;
  genre: string;
  language: string;
  total_chapters: number;
  total_duration_seconds: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Chapter {
  id: string;
  book_id: string;
  chapter_number: number;
  title: string;
  duration_seconds: number;
  status: string;
  created_at: string;
}

export interface ChapterDetail extends Chapter {
  text_content: string | null;
  audio_storage_path: string | null;
}

export interface AudioInfo {
  audio_url: string;
  duration_seconds: number;
}

export interface AudioStatus {
  book_id: string;
  total_chapters: number;
  ready: number;
  generating: number;
  pending: number;
  error: number;
  processed: number;
  completed: boolean;
  is_running: boolean;
  can_start: boolean;
  can_retry_failed: boolean;
  total_duration_seconds: number;
  progress_percent: number;
  chapters: Chapter[];
}

export interface PipelineState {
  step: string;
  current_chapter: number | null;
  current_chapter_title: string;
  chunk_progress: { completed: number; total: number };
}

export interface ApiUsageStats {
  elevenlabs: {
    chars_used: number;
    chars_remaining: number;
    all_exhausted: boolean;
    active_provider: string;
    keys: Array<{
      key_suffix: string;
      chars_used_this_month: number;
      chars_limit: number;
      chars_remaining: number;
      active: boolean;
      exhausted: boolean;
    }>;
  };
  gemini: {
    input_tokens: number;
    output_tokens: number;
    total_requests: number;
    failed_requests: number;
  };
}

export interface EnhancedAudioStatus extends AudioStatus {
  pipeline: PipelineState;
  api_usage: ApiUsageStats;
}

export interface AudioGenerationResponse {
  started: boolean;
  message: string;
  status: AudioStatus;
}

export interface ElevenLabsKeyInfo {
  key: string;
  chars_used: number;
  chars_limit: number | string;
  chars_remaining: number | string;
  active: boolean;
  exhausted: boolean;
}

export interface QuotaCheck {
  book_id: string;
  total_chapters: number;
  pending_chapters: number;
  already_ready: number;
  total_chars_needed: number;
  total_book_chars: number;
  elevenlabs: {
    configured: boolean;
    key_count: number;
    limit_per_key: number;
    total_budget: number;
    chars_used_this_month: number;
    chars_remaining: number;
    can_cover_full_book: boolean;
    coverage_percent: number;
    all_exhausted: boolean;
    keys: ElevenLabsKeyInfo[];
  };
  gemini: {
    configured: boolean;
    key_count: number;
    estimated_tokens: number;
    daily_token_limit: number;
    can_segment: boolean;
  };
  edge_tts: {
    available: boolean;
    note: string;
  };
  verdict: "ready" | "partial" | "fallback";
  verdict_message: string;
}

export interface DeleteBookResponse {
  deleted: boolean;
  book_id: string;
  title: string;
  removed_files: number;
  storage_cleanup_complete: boolean;
  storage_warnings: string[];
}

export interface Progress {
  id: string;
  user_id: string;
  book_id: string;
  chapter_id: string;
  progress_seconds: number;
  completed: boolean;
  last_played_at: string;
}

// --- Book APIs ---

export async function getBooks(genre?: string): Promise<{ books: Book[]; total: number }> {
  const params = new URLSearchParams();
  if (genre) params.set("genre", genre);
  return fetchAPI(`/api/books?${params}`);
}

export async function getBook(id: string): Promise<Book> {
  return fetchAPI(`/api/books/${id}`);
}

export async function deleteBook(id: string): Promise<DeleteBookResponse> {
  return fetchAPI(`/api/books/${id}`, { method: "DELETE" });
}

export async function updateBookMetadata(id: string, formData: FormData): Promise<Book> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000);

  try {
    const res = await fetch(`${API_URL}/api/books/${id}/metadata`, {
      method: "PATCH",
      body: formData,
      signal: controller.signal,
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "Update failed");
    }
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

export interface LLMFailureError {
  error: "llm_processing_failed";
  message: string;
  book_id: string;
  can_retry_with_fallback: boolean;
}

export class UploadLLMError extends Error {
  public data: LLMFailureError;
  constructor(data: LLMFailureError) {
    super(data.message);
    this.name = "UploadLLMError";
    this.data = data;
  }
}

export async function uploadBook(formData: FormData): Promise<Book> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120_000);

  try {
    const res = await fetch(`${API_URL}/api/books/upload`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      // Check for LLM failure response (422)
      if (res.status === 422 && error?.detail?.error === "llm_processing_failed") {
        throw new UploadLLMError(error.detail);
      }
      throw new Error(typeof error.detail === "string" ? error.detail : "Upload failed");
    }
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function retryWithFallback(bookId: string): Promise<Book> {
  return fetchAPI(`/api/books/retry-fallback/${bookId}`, { method: "POST" });
}

// --- Chapter APIs ---

export async function getChapters(bookId: string): Promise<Chapter[]> {
  return fetchAPI(`/api/chapters/book/${bookId}`);
}

// --- Audio APIs ---

export async function generateNextChapter(bookId: string): Promise<{
  done: boolean;
  chapter_number?: number;
  status?: string;
  duration?: number;
  error?: string;
  message?: string;
}> {
  return fetchAPI(`/api/audio/generate-next/${bookId}`, { method: "POST" });
}

export async function startAudioGeneration(
  bookId: string,
  retryFailed = false
): Promise<AudioGenerationResponse> {
  const params = new URLSearchParams();
  if (retryFailed) params.set("retry_failed", "true");
  const query = params.toString();
  return fetchAPI(`/api/audio/start/${bookId}${query ? `?${query}` : ""}`, {
    method: "POST",
  });
}

export async function getAudioStatus(bookId: string): Promise<AudioStatus> {
  return fetchAPI(`/api/audio/status/${bookId}`);
}

export async function getEnhancedStatus(bookId: string): Promise<EnhancedAudioStatus> {
  return fetchAPI(`/api/audio/enhanced-status/${bookId}`);
}

export function createSSEConnection(bookId: string): EventSource {
  return new EventSource(`${API_URL}/api/audio/events/${bookId}`);
}

export async function getAudioStream(bookId: string, chapterNumber: number): Promise<AudioInfo> {
  return fetchAPI(`/api/audio/stream/${bookId}/${chapterNumber}`);
}

export async function getQuotaCheck(bookId: string): Promise<QuotaCheck> {
  return fetchAPI(`/api/audio/quota-check/${bookId}`);
}

// --- Discovery APIs ---

export async function getGenres(options?: RequestInit): Promise<{ genres: string[] }> {
  return fetchAPI("/api/discover/genres", options);
}

export async function getFeaturedBooks(options?: RequestInit): Promise<Book[]> {
  return fetchAPI("/api/discover/featured", options);
}

export async function getBooksByGenre(genre: string, options?: RequestInit): Promise<Book[]> {
  return fetchAPI(`/api/discover/by-genre/${encodeURIComponent(genre)}`, options);
}

export async function getRecentBooks(options?: RequestInit): Promise<Book[]> {
  return fetchAPI("/api/discover/recent", options);
}

export async function getSimilarBooks(bookId: string): Promise<Book[]> {
  return fetchAPI(`/api/discover/similar/${bookId}`);
}

// --- Progress APIs (require auth token) ---

function authHeaders(token: string) {
  return { Authorization: `Bearer ${token}` };
}

export async function getProgress(bookId: string, token: string): Promise<Progress | null> {
  return fetchAPI(`/api/progress/${bookId}`, { headers: authHeaders(token) });
}

export async function updateProgress(
  bookId: string,
  data: { chapter_id: string; progress_seconds: number; completed?: boolean },
  token: string
): Promise<Progress> {
  return fetchAPI(`/api/progress/${bookId}`, {
    method: "PUT",
    body: JSON.stringify(data),
    headers: authHeaders(token),
  });
}

export async function getContinueListening(token: string): Promise<Progress[]> {
  return fetchAPI("/api/progress", { headers: authHeaders(token) });
}

// --- Favorites APIs (require auth token) ---

export async function getFavorites(token: string): Promise<{ id: string; book_id: string }[]> {
  return fetchAPI("/api/favorites", { headers: authHeaders(token) });
}

export async function addFavorite(bookId: string, token: string): Promise<void> {
  await fetchAPI(`/api/favorites/${bookId}`, { method: "POST", headers: authHeaders(token) });
}

export async function removeFavorite(bookId: string, token: string): Promise<void> {
  await fetchAPI(`/api/favorites/${bookId}`, { method: "DELETE", headers: authHeaders(token) });
}

// --- Search (client-side filter for now) ---

export async function searchBooks(query: string): Promise<Book[]> {
  const { books } = await getBooks();
  const q = query.toLowerCase();
  return books.filter(
    (b) =>
      b.title.toLowerCase().includes(q) ||
      b.author.toLowerCase().includes(q) ||
      b.genre.toLowerCase().includes(q)
  );
}
