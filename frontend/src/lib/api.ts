/**
 * API client for communicating with the FastAPI backend.
 *
 * Production-optimized: shorter timeouts, proper abort handling,
 * and no unnecessary wrapper overhead.
 */

import { supabase } from "@/lib/supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "";

// Default timeout for API calls (10s is plenty for DB queries; audio gen uses its own)
const DEFAULT_TIMEOUT_MS = 10_000;
const UPLOAD_TIMEOUT_MS = 300_000;
const FALLBACK_TIMEOUT_MS = 300_000;

type APIRequestOptions = RequestInit & {
  timeoutMs?: number;
};

async function fetchAPI<T>(
  endpoint: string,
  options?: APIRequestOptions
): Promise<T> {
  const controller = new AbortController();
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options ?? {};
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_URL}${endpoint}`, {
      ...fetchOptions,
      signal: fetchOptions.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        ...fetchOptions.headers,
      },
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "API request failed");
    }
    return res.json();
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.ceil(timeoutMs / 1000)} seconds.`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

function buildSupabasePublicUrl(bucket: string, path: string): string {
  if (!SUPABASE_URL) {
    throw new Error("Supabase URL is not configured");
  }
  const normalized = path.replace(/^\/+/, "");
  const encoded = normalized.split("/").map(encodeURIComponent).join("/");
  return `${SUPABASE_URL}/storage/v1/object/public/${bucket}/${encoded}`;
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
  translation_target_language?: string | null;
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

async function getBooksFromSupabase(
  genre?: string,
  limit = 20,
  offset = 0
): Promise<{ books: Book[]; total: number }> {
  let countQuery = supabase
    .from("books")
    .select("id", { count: "exact", head: true })
    .eq("status", "ready");

  let booksQuery = supabase
    .from("books")
    .select("*")
    .eq("status", "ready")
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (genre) {
    countQuery = countQuery.eq("genre", genre);
    booksQuery = booksQuery.eq("genre", genre);
  }

  const [{ count, error: countError }, { data, error: dataError }] = await Promise.all([
    countQuery,
    booksQuery,
  ]);

  if (countError) {
    throw new Error(countError.message);
  }
  if (dataError) {
    throw new Error(dataError.message);
  }

  return {
    books: (data ?? []) as Book[],
    total: count ?? (data?.length ?? 0),
  };
}

async function getBookFromSupabase(id: string): Promise<Book | null> {
  const { data, error } = await supabase
    .from("books")
    .select("*")
    .eq("id", id)
    .maybeSingle();

  if (error) {
    throw new Error(error.message);
  }
  return (data as Book | null) ?? null;
}

async function getChaptersFromSupabase(bookId: string): Promise<Chapter[]> {
  const { data, error } = await supabase
    .from("chapters")
    .select("id,book_id,chapter_number,title,duration_seconds,status,created_at")
    .eq("book_id", bookId)
    .order("chapter_number", { ascending: true });

  if (error) {
    throw new Error(error.message);
  }
  return (data ?? []) as Chapter[];
}

async function getAudioInfoFromSupabase(bookId: string, chapterNumber: number): Promise<AudioInfo | null> {
  const { data, error } = await supabase
    .from("chapters")
    .select("status,audio_storage_path,duration_seconds")
    .eq("book_id", bookId)
    .eq("chapter_number", chapterNumber)
    .maybeSingle();

  if (error) {
    throw new Error(error.message);
  }
  if (!data) {
    return null;
  }
  if (data.status !== "ready" || !data.audio_storage_path) {
    throw new Error("Audio not yet generated");
  }

  return {
    audio_url: buildSupabasePublicUrl("audiobooks", data.audio_storage_path),
    duration_seconds: data.duration_seconds ?? 0,
  };
}

// --- Book APIs ---

export async function getBooks(genre?: string): Promise<{ books: Book[]; total: number }> {
  try {
    return await getBooksFromSupabase(genre);
  } catch {
    const params = new URLSearchParams();
    if (genre) params.set("genre", genre);
    return fetchAPI(`/api/books?${params}`);
  }
}

export async function getBook(id: string): Promise<Book> {
  try {
    const book = await getBookFromSupabase(id);
    if (book) return book;
  } catch {
    // Fallback to backend API
  }
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

export interface QuotaFailureError {
  error: "llm_quota_exhausted" | "llm_auth_failed";
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

export class UploadQuotaError extends Error {
  public data: QuotaFailureError & {
    can_provide_new_key: boolean;
    exhausted_provider: string;
  };
  constructor(
    data: QuotaFailureError & {
      can_provide_new_key: boolean;
      exhausted_provider: string;
    }
  ) {
    super(data.message);
    this.name = "UploadQuotaError";
    this.data = data;
  }
}

export async function uploadBook(formData: FormData): Promise<Book> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_URL}/api/books/upload`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      // Check for quota exhaustion or auth failure response (422)
      if (
        res.status === 422 &&
        (error?.detail?.error === "llm_quota_exhausted" ||
          error?.detail?.error === "llm_auth_failed")
      ) {
        throw new UploadQuotaError(error.detail);
      }
      // Check for LLM failure response (422)
      if (res.status === 422 && error?.detail?.error === "llm_processing_failed") {
        throw new UploadLLMError(error.detail);
      }
      throw new Error(typeof error.detail === "string" ? error.detail : "Upload failed");
    }
    return res.json();
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Upload timed out after ${Math.ceil(UPLOAD_TIMEOUT_MS / 1000)} seconds.`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function retryWithFallback(bookId: string): Promise<Book> {
  return fetchAPI(`/api/books/retry-fallback/${bookId}`, {
    method: "POST",
    timeoutMs: FALLBACK_TIMEOUT_MS,
  });
}

// --- Chapter APIs ---

export async function getChapters(bookId: string): Promise<Chapter[]> {
  try {
    const chapters = await getChaptersFromSupabase(bookId);
    if (chapters.length > 0) return chapters;
  } catch {
    // Fallback to backend API
  }
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
  try {
    const info = await getAudioInfoFromSupabase(bookId, chapterNumber);
    if (info) return info;
  } catch {
    // Fallback to backend API
  }
  return fetchAPI(`/api/audio/stream/${bookId}/${chapterNumber}`);
}

export async function getQuotaCheck(bookId: string): Promise<QuotaCheck> {
  return fetchAPI(`/api/audio/quota-check/${bookId}`);
}

export async function addApiKey(
  provider: string,
  apiKey: string,
  persist = true
): Promise<{ success: boolean; message: string }> {
  return fetchAPI("/api/audio/add-api-key", {
    method: "POST",
    body: JSON.stringify({ provider, api_key: apiKey, persist }),
  });
}

// --- Discovery APIs ---

export async function getGenres(options?: RequestInit): Promise<{ genres: string[] }> {
  try {
    const { data, error } = await supabase
      .from("books")
      .select("genre")
      .eq("status", "ready");

    if (error) throw new Error(error.message);

    const genres = Array.from(new Set((data ?? []).map((row) => row.genre).filter(Boolean))).sort();
    return { genres };
  } catch {
    return fetchAPI("/api/discover/genres", options);
  }
}

export async function getFeaturedBooks(options?: RequestInit): Promise<Book[]> {
  try {
    const { books } = await getBooksFromSupabase(undefined, 5, 0);
    return books;
  } catch {
    return fetchAPI("/api/discover/featured", options);
  }
}

export async function getBooksByGenre(genre: string, options?: RequestInit): Promise<Book[]> {
  try {
    const { books } = await getBooksFromSupabase(genre, 10, 0);
    return books;
  } catch {
    return fetchAPI(`/api/discover/by-genre/${encodeURIComponent(genre)}`, options);
  }
}

export async function getRecentBooks(options?: RequestInit): Promise<Book[]> {
  try {
    const { books } = await getBooksFromSupabase(undefined, 10, 0);
    return books;
  } catch {
    return fetchAPI("/api/discover/recent", options);
  }
}

export async function getSimilarBooks(bookId: string): Promise<Book[]> {
  try {
    const sourceBook = await getBookFromSupabase(bookId);
    if (sourceBook) {
      const { data, error } = await supabase
        .from("books")
        .select("*")
        .eq("status", "ready")
        .eq("genre", sourceBook.genre)
        .neq("id", bookId)
        .order("created_at", { ascending: false })
        .limit(6);

      if (error) throw new Error(error.message);
      return (data ?? []) as Book[];
    }
  } catch {
    // Fallback to backend API
  }
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
