"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle, Clock, Loader2, Mic, Radio } from "lucide-react";

import {
  AudioStatus,
  createSSEConnection,
  getAudioStatus,
  startAudioGeneration,
} from "@/lib/api";

interface AudioProgressTrackerProps {
  bookId: string;
  startRequestKey?: number;
  retryFailed?: boolean;
  onComplete: (status: AudioStatus) => void;
  onStatusChange?: (status: AudioStatus) => void;
}

const POLL_INTERVAL_MS = 3000; // Fallback polling interval (SSE is primary)

function formatETA(seconds: number): string {
  if (seconds < 60) return `${Math.ceil(seconds)}s`;
  const mins = Math.ceil(seconds / 60);
  if (mins < 60) return `~${mins}m`;
  const hrs = Math.floor(mins / 60);
  return `~${hrs}h ${mins % 60}m`;
}

const STEP_LABELS: Record<string, string> = {
  idle: "Waiting",
  extracting_pdf: "Extracting PDF",
  structuring_chapters: "Structuring Chapters",
  generating_audio: "Generating Audio",
  complete: "Complete",
};

export default function AudioProgressTracker({
  bookId,
  startRequestKey = 0,
  retryFailed = false,
  onComplete,
  onStatusChange,
}: AudioProgressTrackerProps) {
  const [status, setStatus] = useState<AudioStatus | null>(null);
  const [eta, setEta] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [requestError, setRequestError] = useState<string | null>(null);
  const [sseConnected, setSseConnected] = useState(false);
  const [pipelineStep, setPipelineStep] = useState("idle");
  const [chunkProgress, setChunkProgress] = useState<{ completed: number; total: number }>({ completed: 0, total: 0 });

  const mountedRef = useRef(true);
  const notifiedCompleteRef = useRef(false);
  const startTimeRef = useRef<number | null>(null);
  const startProcessedRef = useRef<number | null>(null);

  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const applyStatus = useCallback((nextStatus: AudioStatus, message?: string) => {
    setStatus(nextStatus);
    onStatusChangeRef.current?.(nextStatus);

    if (message) {
      setStatusMessage(message);
    } else {
      const activeChapter = nextStatus.chapters.find((ch) => ch.status === "generating");
      if (activeChapter) {
        setStatusMessage(`Generating chapter ${activeChapter.chapter_number}: ${activeChapter.title}`);
      } else if (nextStatus.completed && nextStatus.error > 0) {
        setStatusMessage(`Generation finished with ${nextStatus.error} failed chapter(s).`);
      } else if (nextStatus.completed) {
        setStatusMessage("Audio generation complete.");
      } else if (!nextStatus.is_running && nextStatus.pending > 0) {
        setStatusMessage("Generation is paused. Resume when you're ready.");
      } else {
        setStatusMessage("");
      }
    }

    if (startProcessedRef.current === null || nextStatus.processed < startProcessedRef.current) {
      startProcessedRef.current = nextStatus.processed;
      startTimeRef.current = Date.now();
    }

    const processedSinceStart = nextStatus.processed - (startProcessedRef.current ?? 0);
    const remaining = nextStatus.total_chapters - nextStatus.processed;
    if (processedSinceStart > 0 && remaining > 0 && startTimeRef.current) {
      const elapsedSeconds = (Date.now() - startTimeRef.current) / 1000;
      const avgSecondsPerChapter = elapsedSeconds / processedSinceStart;
      setEta(formatETA(avgSecondsPerChapter * remaining));
    } else if (nextStatus.completed || remaining <= 0) {
      setEta("");
    }

    if (nextStatus.completed && !nextStatus.is_running && !notifiedCompleteRef.current) {
      notifiedCompleteRef.current = true;
      onCompleteRef.current(nextStatus);
    }
  }, []);

  // SSE connection for real-time chunk-level updates
  useEffect(() => {
    const es = createSSEConnection(bookId);

    es.onopen = () => setSseConnected(true);
    es.onerror = () => setSseConnected(false);

    const handleEvent = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data);
        const data = event.data;

        switch (event.type) {
          case "snapshot":
            setPipelineStep((data.step as string) || "idle");
            setChunkProgress(data.chunk_progress || { completed: 0, total: 0 });
            break;
          case "step_change":
            setPipelineStep((data.step as string) || "idle");
            break;
          case "chapter_start":
            setChunkProgress({ completed: 0, total: 0 });
            setStatusMessage(`Generating chapter ${data.chapter_number}: ${data.title}`);
            break;
          case "chunk_progress":
            setChunkProgress({ completed: data.completed ?? 0, total: data.total ?? 0 });
            break;
          case "chapter_done":
            setChunkProgress({ completed: 0, total: 0 });
            // Refresh full status from server after each chapter completes
            getAudioStatus(bookId)
              .then((s) => { if (mountedRef.current) applyStatus(s); })
              .catch(() => {});
            break;
          case "complete":
            setPipelineStep("complete");
            getAudioStatus(bookId)
              .then((s) => { if (mountedRef.current) applyStatus(s); })
              .catch(() => {});
            break;
        }
      } catch {
        // Ignore malformed events
      }
    };

    for (const type of ["snapshot", "step_change", "chapter_start", "chunk_progress", "chapter_done", "api_usage", "complete"]) {
      es.addEventListener(type, handleEvent);
    }

    return () => { es.close(); setSseConnected(false); };
  }, [bookId, applyStatus]);

  // Initial start + fallback polling
  useEffect(() => {
    mountedRef.current = true;
    notifiedCompleteRef.current = false;
    startProcessedRef.current = null;
    startTimeRef.current = null;

    let intervalId: ReturnType<typeof setInterval> | null = null;

    const refreshStatus = async () => {
      try {
        const nextStatus = await getAudioStatus(bookId);
        if (!mountedRef.current) return;
        setRequestError(null);
        applyStatus(nextStatus);

        if (nextStatus.completed && !nextStatus.is_running && intervalId) {
          clearInterval(intervalId);
          intervalId = null;
        }
      } catch (err) {
        if (!mountedRef.current) return;
        setRequestError(err instanceof Error ? err.message : "Failed to refresh audio status.");
      }
    };

    const init = async () => {
      try {
        if (startRequestKey > 0) {
          const response = await startAudioGeneration(bookId, retryFailed);
          if (!mountedRef.current) return;
          setRequestError(null);
          applyStatus(response.status, response.message);
        } else {
          await refreshStatus();
        }
      } catch (err) {
        if (!mountedRef.current) return;
        const errorMsg = err instanceof Error ? err.message : "Failed to start audio generation.";
        setRequestError(errorMsg);
      }

      // Fallback polling — SSE handles real-time updates, but polling ensures
      // we still get full status refreshes periodically
      intervalId = setInterval(() => {
        void refreshStatus();
      }, POLL_INTERVAL_MS);
    };

    void init();

    return () => {
      mountedRef.current = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [bookId, retryFailed, startRequestKey, applyStatus]);

  if (!status) {
    return (
      <div className="surface-card rounded-[2rem] p-8 text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Loader2 className="size-6 animate-spin" />
        </div>
        <p className="mt-4 text-muted-foreground">
          {startRequestKey > 0 ? "Starting audio generation..." : "Loading audio status..."}
        </p>
        {requestError && <p className="mt-2 text-sm text-destructive">{requestError}</p>}
      </div>
    );
  }

  const { total_chapters, ready, generating, error, progress_percent } = status;
  const chunkPct =
    chunkProgress.total > 0
      ? Math.round((chunkProgress.completed / chunkProgress.total) * 100)
      : 0;

  return (
    <div className="surface-card rounded-[2rem] p-6 md:p-8">
      <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-4">
          <div className="flex size-12 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Mic className="size-5" />
          </div>
          <div className="space-y-1">
            <h3 className="text-xl font-semibold tracking-tight text-foreground">Audio Generation</h3>
            <p className="text-sm text-muted-foreground">
              {ready} ready of {total_chapters}
              {error > 0 && ` - ${error} failed`}
              {generating > 0 && " - in progress"}
            </p>
            {/* Pipeline step indicator */}
            {pipelineStep !== "idle" && pipelineStep !== "complete" && (
              <div className="flex items-center gap-1.5 mt-1">
                <div className="size-1.5 rounded-full bg-foreground animate-pulse" />
                <span className="text-xs text-muted-foreground">
                  {STEP_LABELS[pipelineStep] || pipelineStep}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="text-left md:text-right">
          <p className="text-3xl font-semibold tracking-tight text-foreground">{progress_percent}%</p>
          <div className="flex items-center gap-3 mt-1 justify-start md:justify-end">
            {eta && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Clock className="size-3.5" />
                ETA: {eta}
              </span>
            )}
            <span className="inline-flex items-center gap-1 text-[0.6rem] text-muted-foreground">
              <Radio className={`size-2.5 ${sseConnected ? "text-emerald-500" : "text-muted-foreground"}`} />
              {sseConnected ? "Live" : "Polling"}
            </span>
          </div>
        </div>
      </div>

      <div className="mt-6 space-y-3">
        {/* Main progress bar */}
        <div className="h-3 overflow-hidden rounded-full bg-muted">
          {progress_percent === 0 && status.is_running ? (
            <div className="relative h-full w-1/3 rounded-full bg-primary animate-[indeterminate_1.8s_ease-in-out_infinite]">
              <div className="animate-shimmer absolute inset-0 bg-gradient-to-r from-transparent via-primary-foreground/20 to-transparent" />
            </div>
          ) : (
            <div
              className="relative h-full rounded-full bg-primary transition-[width] duration-700 ease-out"
              style={{ width: `${progress_percent}%` }}
            >
              {progress_percent < 100 && status.is_running && (
                <div className="animate-shimmer absolute inset-0 bg-gradient-to-r from-transparent via-primary-foreground/20 to-transparent" />
              )}
            </div>
          )}
        </div>

        {/* Chunk sub-progress bar (shown when a chapter is actively generating) */}
        {chunkProgress.total > 1 && generating > 0 && (
          <div className="space-y-1">
            <div className="flex justify-between text-[0.65rem] text-muted-foreground">
              <span>Chunk progress</span>
              <span>
                {chunkProgress.completed}/{chunkProgress.total} ({chunkPct}%)
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-foreground/50 transition-[width] duration-500 ease-out"
                style={{ width: `${chunkPct}%` }}
              />
            </div>
          </div>
        )}

        {statusMessage && <p className="text-sm text-muted-foreground">{statusMessage}</p>}
        {requestError && <p className="text-sm text-destructive">{requestError}</p>}
      </div>

      <div className="mt-6 max-h-72 space-y-2 overflow-y-auto pr-2 scrollbar-thin">
        {status.chapters.map((chapter) => (
          <div
            key={chapter.id}
            className={`flex items-center justify-between gap-3 rounded-[1.25rem] border px-4 py-3 text-sm ${
              chapter.status === "ready"
                ? "border-border/70 bg-background/55"
                : chapter.status === "generating"
                  ? "border-border/70 bg-foreground/[0.04]"
                  : chapter.status === "error"
                    ? "border-destructive/20 bg-destructive/5"
                    : "border-border/50 bg-muted/50"
            }`}
          >
            <div className="flex min-w-0 items-center gap-3">
              {chapter.status === "ready" ? (
                <CheckCircle className="size-4 shrink-0 text-foreground" />
              ) : chapter.status === "generating" ? (
                <Loader2 className="size-4 shrink-0 animate-spin text-foreground" />
              ) : chapter.status === "error" ? (
                <AlertCircle className="size-4 shrink-0 text-destructive" />
              ) : (
                <div className="size-4 shrink-0 rounded-full border border-border/80" />
              )}
              <span className="truncate text-foreground">
                Chapter {chapter.chapter_number}: {chapter.title}
              </span>
            </div>
            <span className="shrink-0 text-xs text-muted-foreground">
              {chapter.status === "ready"
                ? `${Math.floor(chapter.duration_seconds / 60)}m ${chapter.duration_seconds % 60}s`
                : chapter.status === "generating"
                  ? chunkProgress.total > 0
                    ? `${chunkPct}%`
                    : "Working..."
                  : chapter.status === "error"
                    ? "Failed"
                    : "Pending"}
            </span>
          </div>
        ))}
      </div>

      {/* Status indicator at bottom — no unnecessary text */}
    </div>
  );
}
