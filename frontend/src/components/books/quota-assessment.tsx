"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle,
  AlertTriangle,
  Info,
  Zap,
  Key,
  Brain,
  Volume2,
} from "lucide-react";

import { getQuotaCheck, QuotaCheck } from "@/lib/api";

interface QuotaAssessmentProps {
  bookId: string;
  /** Hide the assessment once generation has started */
  hidden?: boolean;
}

function fmtChars(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function pctBar(pct: number, color: string) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={`h-full rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  );
}

export default function QuotaAssessment({ bookId, hidden }: QuotaAssessmentProps) {
  const [quota, setQuota] = useState<QuotaCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getQuotaCheck(bookId);
        if (!cancelled) setQuota(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to check quota");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [bookId]);

  if (hidden || loading || error || !quota || quota.pending_chapters === 0) {
    return null;
  }

  const el = quota.elevenlabs;
  const gm = quota.gemini;
  const isReady = quota.verdict === "ready";
  const isPartial = quota.verdict === "partial";

  // Verdict styling
  const verdictIcon = isReady ? (
    <CheckCircle className="size-5 text-emerald-500" />
  ) : isPartial ? (
    <AlertTriangle className="size-5 text-amber-500" />
  ) : (
    <Info className="size-5 text-blue-500" />
  );

  const verdictBorder = isReady
    ? "border-emerald-500/20"
    : isPartial
      ? "border-amber-500/20"
      : "border-blue-500/20";

  const verdictBg = isReady
    ? "bg-emerald-500/5"
    : isPartial
      ? "bg-amber-500/5"
      : "bg-blue-500/5";

  return (
    <div className={`surface-card rounded-[2rem] overflow-hidden border ${verdictBorder}`}>
      {/* Header banner */}
      <div className={`px-6 py-4 ${verdictBg}`}>
        <div className="flex items-start gap-3">
          {verdictIcon}
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold tracking-tight text-foreground">
              Pre-Generation Quota Check
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {quota.verdict_message}
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-5 px-6 py-5">
        {/* Book text overview */}
        <div className="flex items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-foreground/[0.06]">
            <Zap className="size-4 text-foreground/70" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">
              {quota.pending_chapters} chapter{quota.pending_chapters !== 1 ? "s" : ""} need audio
            </p>
            <p className="text-xs text-muted-foreground">
              {fmtChars(quota.total_chars_needed)} characters to convert to speech
              {quota.already_ready > 0 && ` (${quota.already_ready} already done)`}
            </p>
          </div>
        </div>

        {/* ElevenLabs section */}
        <div className="rounded-2xl border border-border/70 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Volume2 className="size-4 text-foreground/70" />
            <span className="text-sm font-semibold text-foreground">ElevenLabs TTS</span>
            {el.configured ? (
              <span className="ml-auto rounded-full bg-emerald-500/10 px-2 py-0.5 text-[0.65rem] font-medium text-emerald-600 dark:text-emerald-400">
                {el.key_count} key{el.key_count !== 1 ? "s" : ""} active
              </span>
            ) : (
              <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[0.65rem] font-medium text-muted-foreground">
                Not configured
              </span>
            )}
          </div>

          {el.configured && (
            <>
              {/* Overall budget bar */}
              <div>
                <div className="mb-1.5 flex items-baseline justify-between text-xs">
                  <span className="text-muted-foreground">
                    Monthly budget: {fmtChars(el.chars_used_this_month)} / {fmtChars(el.total_budget)} used
                  </span>
                  <span className="font-medium text-foreground">
                    {fmtChars(el.chars_remaining)} left
                  </span>
                </div>
                {pctBar(
                  (el.chars_used_this_month / el.total_budget) * 100,
                  el.all_exhausted ? "bg-red-500" : el.coverage_percent < 100 ? "bg-amber-500" : "bg-emerald-500"
                )}
              </div>

              {/* Per-key breakdown */}
              <div className="space-y-2">
                {el.keys.map((k, i) => {
                  const used = typeof k.chars_used === "number" ? k.chars_used : 0;
                  const limit = typeof k.chars_limit === "number" ? k.chars_limit : 10000;
                  const remaining = typeof k.chars_remaining === "number" ? k.chars_remaining : limit - used;
                  const usedPct = (used / limit) * 100;

                  return (
                    <div key={i} className="flex items-center gap-3">
                      <Key className="size-3 shrink-0 text-muted-foreground/60" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between text-[0.7rem]">
                          <span className="text-muted-foreground">
                            Key {k.key}
                            {k.active && (
                              <span className="ml-1 text-emerald-500">●</span>
                            )}
                            {k.exhausted && (
                              <span className="ml-1 text-red-400">(exhausted)</span>
                            )}
                          </span>
                          <span className="text-foreground/80">
                            {fmtChars(used)} / {fmtChars(limit)}
                          </span>
                        </div>
                        {pctBar(usedPct, k.exhausted ? "bg-red-400" : "bg-foreground/30")}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Coverage assessment */}
              {quota.total_chars_needed > 0 && (
                <div className="rounded-xl bg-foreground/[0.03] px-3 py-2 text-xs text-muted-foreground">
                  {el.can_cover_full_book ? (
                    <span className="text-emerald-600 dark:text-emerald-400">
                      ✓ ElevenLabs can fully generate this book ({fmtChars(quota.total_chars_needed)} needed,{" "}
                      {fmtChars(el.chars_remaining)} available)
                    </span>
                  ) : el.chars_remaining > 0 ? (
                    <span>
                      ElevenLabs will handle ~{el.coverage_percent}% ({fmtChars(el.chars_remaining)} chars),
                      then Edge-TTS covers the rest seamlessly
                    </span>
                  ) : (
                    <span className="text-amber-600 dark:text-amber-400">
                      Monthly quota fully used — Edge-TTS will handle all audio
                    </span>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Gemini LLM section */}
        <div className="rounded-2xl border border-border/70 p-4 space-y-2">
          <div className="flex items-center gap-2">
            <Brain className="size-4 text-foreground/70" />
            <span className="text-sm font-semibold text-foreground">Gemini AI (Chapter Segmentation)</span>
            {gm.configured ? (
              <span className="ml-auto rounded-full bg-emerald-500/10 px-2 py-0.5 text-[0.65rem] font-medium text-emerald-600 dark:text-emerald-400">
                {gm.key_count} key{gm.key_count !== 1 ? "s" : ""} active
              </span>
            ) : (
              <span className="ml-auto rounded-full bg-amber-500/10 px-2 py-0.5 text-[0.65rem] font-medium text-amber-600 dark:text-amber-400">
                Not configured
              </span>
            )}
          </div>

          {gm.configured ? (
            <div className="text-xs text-muted-foreground space-y-1">
              <p>
                Book size: ~{fmtChars(gm.estimated_tokens)} tokens
                (daily limit: {fmtChars(gm.daily_token_limit)} tokens)
              </p>
              {gm.can_segment ? (
                <p className="text-emerald-600 dark:text-emerald-400">
                  ✓ Gemini can segment this book into intelligent chapters
                </p>
              ) : (
                <p className="text-amber-600 dark:text-amber-400">
                  Book is very large — segmentation will use regex fallback
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Chapter segmentation will use pattern matching (regex) instead of AI.
              Add a free Gemini API key for smarter chapter detection.
            </p>
          )}
        </div>

        {/* Edge-TTS always-available note */}
        {(!el.configured || el.all_exhausted || !el.can_cover_full_book) && (
          <div className="flex items-start gap-2 rounded-xl bg-blue-500/5 px-4 py-3 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0 text-blue-500" />
            <span>
              <strong className="text-foreground">Edge-TTS</strong> is always available as a free,
              unlimited fallback. Audio generation will never fail due to quota limits —
              it seamlessly switches providers when needed.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
