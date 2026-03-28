"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Brain,
  Key,
  Radio,
  Volume2,
  Zap,
} from "lucide-react";

import { ApiUsageStats, createSSEConnection, PipelineState } from "@/lib/api";

interface LiveStatusPanelProps {
  bookId: string;
  /** Only show when generation is actively running */
  visible: boolean;
}

interface SSEEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

const STEP_LABELS: Record<string, string> = {
  idle: "Idle",
  extracting_pdf: "Extracting PDF",
  structuring_chapters: "Structuring Chapters",
  generating_audio: "Generating Audio",
  complete: "Complete",
};

const STEP_ORDER = ["extracting_pdf", "structuring_chapters", "generating_audio", "complete"];

function fmtChars(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function pctBar(pct: number, color: string) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={`h-full rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  );
}

export default function LiveStatusPanel({ bookId, visible }: LiveStatusPanelProps) {
  const [pipeline, setPipeline] = useState<PipelineState>({
    step: "idle",
    current_chapter: null,
    current_chapter_title: "",
    chunk_progress: { completed: 0, total: 0 },
  });

  const [apiUsage, setApiUsage] = useState<ApiUsageStats | null>(null);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!visible) {
      // Cleanup SSE when not visible
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
        setConnected(false);
      }
      return;
    }

    const es = createSSEConnection(bookId);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    // Handle all event types
    const handleEvent = (e: MessageEvent) => {
      try {
        const event: SSEEvent = JSON.parse(e.data);
        const data = event.data;

        switch (event.type) {
          case "snapshot":
            setPipeline({
              step: (data.step as string) || "idle",
              current_chapter: (data.current_chapter as number | null) ?? null,
              current_chapter_title: (data.current_chapter_title as string) || "",
              chunk_progress: (data.chunk_progress as { completed: number; total: number }) || { completed: 0, total: 0 },
            });
            if (data.api_usage && Object.keys(data.api_usage as object).length > 0) {
              setApiUsage(data.api_usage as ApiUsageStats);
            }
            break;
          case "step_change":
            setPipeline((prev) => ({ ...prev, step: (data.step as string) || prev.step }));
            break;
          case "chapter_start":
            setPipeline((prev) => ({
              ...prev,
              current_chapter: (data.chapter_number as number) ?? null,
              current_chapter_title: (data.title as string) || "",
              chunk_progress: { completed: 0, total: 0 },
            }));
            break;
          case "chunk_progress":
            setPipeline((prev) => ({
              ...prev,
              chunk_progress: {
                completed: (data.completed as number) ?? 0,
                total: (data.total as number) ?? 0,
              },
            }));
            break;
          case "chapter_done":
            setPipeline((prev) => ({
              ...prev,
              current_chapter: null,
              current_chapter_title: "",
              chunk_progress: { completed: 0, total: 0 },
            }));
            break;
          case "api_usage":
            // The api_usage event data IS the usage object
            setApiUsage((prev) => {
              const d = data as Record<string, unknown>;
              return {
                elevenlabs: {
                  chars_used: (d.elevenlabs_chars_used as number) ?? prev?.elevenlabs.chars_used ?? 0,
                  chars_remaining: (d.elevenlabs_chars_remaining as number) ?? prev?.elevenlabs.chars_remaining ?? 0,
                  all_exhausted: (d.elevenlabs_all_exhausted as boolean) ?? false,
                  active_provider: (d.elevenlabs_active_provider as string) ?? "unknown",
                  keys: (d.elevenlabs_keys as ApiUsageStats["elevenlabs"]["keys"]) ?? prev?.elevenlabs.keys ?? [],
                },
                gemini: {
                  input_tokens: (d.gemini_input_tokens as number) ?? prev?.gemini.input_tokens ?? 0,
                  output_tokens: (d.gemini_output_tokens as number) ?? prev?.gemini.output_tokens ?? 0,
                  total_requests: (d.gemini_total_requests as number) ?? prev?.gemini.total_requests ?? 0,
                  failed_requests: (d.gemini_failed_requests as number) ?? prev?.gemini.failed_requests ?? 0,
                },
              };
            });
            break;
          case "complete":
            setPipeline((prev) => ({ ...prev, step: "complete" }));
            break;
        }
      } catch {
        // Ignore malformed events
      }
    };

    // Listen for each SSE event type
    for (const type of ["snapshot", "step_change", "chapter_start", "chunk_progress", "chapter_done", "api_usage", "complete"]) {
      es.addEventListener(type, handleEvent);
    }

    return () => {
      es.close();
      eventSourceRef.current = null;
      setConnected(false);
    };
  }, [bookId, visible]);

  if (!visible) return null;

  const stepIdx = STEP_ORDER.indexOf(pipeline.step);
  const chunkPct =
    pipeline.chunk_progress.total > 0
      ? Math.round((pipeline.chunk_progress.completed / pipeline.chunk_progress.total) * 100)
      : 0;

  return (
    <div className="surface-card rounded-[2rem] overflow-hidden border border-border/70">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
        <div className="flex items-center gap-2.5">
          <Activity className="size-4 text-foreground/70" />
          <h3 className="text-sm font-semibold tracking-tight text-foreground">
            Live Generation Status
          </h3>
        </div>
        <div className="flex items-center gap-1.5">
          <Radio className={`size-3 ${connected ? "text-emerald-500 animate-pulse" : "text-muted-foreground"}`} />
          <span className="text-[0.65rem] text-muted-foreground">
            {connected ? "Connected" : "Reconnecting..."}
          </span>
        </div>
      </div>

      <div className="space-y-4 px-6 py-5">
        {/* Pipeline steps */}
        <div>
          <p className="text-[0.65rem] font-medium uppercase tracking-[0.2em] text-muted-foreground mb-3">
            Pipeline
          </p>
          <div className="flex items-center gap-1">
            {STEP_ORDER.map((step, i) => {
              const isActive = step === pipeline.step;
              const isDone = stepIdx > i || pipeline.step === "complete";
              return (
                <div key={step} className="flex-1">
                  <div
                    className={`h-1.5 rounded-full transition-all duration-500 ${
                      isDone
                        ? "bg-foreground"
                        : isActive
                          ? "bg-foreground/60"
                          : "bg-muted"
                    }`}
                  />
                  <p
                    className={`mt-1.5 text-[0.6rem] leading-tight ${
                      isActive ? "font-medium text-foreground" : "text-muted-foreground"
                    }`}
                  >
                    {STEP_LABELS[step] || step}
                  </p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Current chapter + chunk progress */}
        {pipeline.current_chapter !== null && (
          <div className="rounded-2xl border border-border/70 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">
                Chapter {pipeline.current_chapter}: {pipeline.current_chapter_title}
              </span>
              {pipeline.chunk_progress.total > 0 && (
                <span className="text-xs text-muted-foreground">
                  {pipeline.chunk_progress.completed}/{pipeline.chunk_progress.total} chunks ({chunkPct}%)
                </span>
              )}
            </div>
            {pipeline.chunk_progress.total > 0 &&
              pctBar(chunkPct, "bg-foreground/70")}
          </div>
        )}

        {/* API Usage section */}
        {apiUsage && (
          <div className="space-y-3">
            <p className="text-[0.65rem] font-medium uppercase tracking-[0.2em] text-muted-foreground">
              API Usage
            </p>

            {/* ElevenLabs */}
            <div className="rounded-2xl border border-border/70 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <Volume2 className="size-3.5 text-foreground/70" />
                <span className="text-xs font-semibold text-foreground">ElevenLabs TTS</span>
                <span className="ml-auto text-[0.6rem] text-muted-foreground">
                  Provider: {apiUsage.elevenlabs.active_provider}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-[0.7rem]">
                <span className="text-muted-foreground">
                  Characters used: {fmtChars(apiUsage.elevenlabs.chars_used)}
                </span>
                <span className="font-medium text-foreground">
                  {fmtChars(apiUsage.elevenlabs.chars_remaining)} remaining
                </span>
              </div>

              {/* Per-key mini bars */}
              {apiUsage.elevenlabs.keys.length > 0 && (
                <div className="space-y-1.5">
                  {apiUsage.elevenlabs.keys.map((k, i) => {
                    const used = k.chars_used_this_month ?? 0;
                    const limit = k.chars_limit ?? 10000;
                    const usedPct = (used / limit) * 100;
                    return (
                      <div key={i} className="flex items-center gap-2">
                        <Key className="size-2.5 shrink-0 text-muted-foreground/60" />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-baseline justify-between text-[0.6rem]">
                            <span className="text-muted-foreground">
                              {k.key_suffix}
                              {k.active && <span className="ml-1 text-emerald-500">●</span>}
                              {k.exhausted && <span className="ml-1 text-red-400">(exhausted)</span>}
                            </span>
                            <span className="text-foreground/80">
                              {fmtChars(used)}/{fmtChars(limit)}
                            </span>
                          </div>
                          {pctBar(usedPct, k.exhausted ? "bg-red-400" : "bg-foreground/30")}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {apiUsage.elevenlabs.all_exhausted && (
                <p className="text-[0.65rem] text-amber-600 dark:text-amber-400">
                  All ElevenLabs keys exhausted — using Edge-TTS fallback
                </p>
              )}
            </div>

            {/* Gemini LLM */}
            <div className="rounded-2xl border border-border/70 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <Brain className="size-3.5 text-foreground/70" />
                <span className="text-xs font-semibold text-foreground">Gemini AI</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[0.7rem]">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Input tokens</span>
                  <span className="font-medium text-foreground">{fmtTokens(apiUsage.gemini.input_tokens)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Output tokens</span>
                  <span className="font-medium text-foreground">{fmtTokens(apiUsage.gemini.output_tokens)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Requests</span>
                  <span className="font-medium text-foreground">{apiUsage.gemini.total_requests}</span>
                </div>
                {apiUsage.gemini.failed_requests > 0 && (
                  <div className="flex justify-between">
                    <span className="text-red-400">Failed</span>
                    <span className="font-medium text-red-400">{apiUsage.gemini.failed_requests}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Step indicator when idle with no usage data yet */}
        {!apiUsage && pipeline.step !== "idle" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Zap className="size-3.5" />
            <span>{STEP_LABELS[pipeline.step] || "Processing"}...</span>
          </div>
        )}
      </div>
    </div>
  );
}
