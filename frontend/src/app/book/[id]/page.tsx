"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, BookOpen, Heart } from "lucide-react";
import Link from "next/link";

import AudioProgressTracker from "@/components/books/audio-progress-tracker";
import QuotaAssessment from "@/components/books/quota-assessment";
import BookRow from "@/components/books/book-row";
import AudioPlayer from "@/components/player/audio-player";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAdmin } from "@/lib/admin-context";
import { AudioStatus, Book, Chapter, getAudioStatus, getBook, getChapters, getSimilarBooks } from "@/lib/api";

function formatDuration(seconds: number): string {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (hrs > 0) return `${hrs}h ${mins}m`;
  return `${mins}m`;
}

export default function BookDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { isAdmin } = useAdmin();
  const bookId = params.id as string;

  const [book, setBook] = useState<Book | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [similar, setSimilar] = useState<Book[]>([]);
  const [audioStatus, setAudioStatus] = useState<AudioStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [showProgressTracker, setShowProgressTracker] = useState(false);
  const [generationRunning, setGenerationRunning] = useState(false);
  const [startRequestKey, setStartRequestKey] = useState(0);
  const [retryFailed, setRetryFailed] = useState(false);
  const [favorited, setFavorited] = useState(false);

  const applyAudioStatus = useCallback((status: AudioStatus) => {
    setAudioStatus(status);
    setChapters(status.chapters);
    setBook((current) =>
      current
        ? {
            ...current,
            total_duration_seconds: status.total_duration_seconds,
          }
        : current
    );
  }, []);

  useEffect(() => {
    async function load() {
      try {
        const [bookData, chapterData, similarData, statusData] = await Promise.all([
          getBook(bookId),
          getChapters(bookId).catch(() => []),
          getSimilarBooks(bookId),
          getAudioStatus(bookId).catch(() => null),
        ]);

        setBook(statusData ? { ...bookData, total_duration_seconds: statusData.total_duration_seconds } : bookData);
        setChapters(statusData?.chapters ?? chapterData);
        setSimilar(similarData);
        setAudioStatus(statusData);
        setGenerationRunning(Boolean(statusData?.is_running));
        setShowProgressTracker(Boolean(statusData && (statusData.is_running || (statusData.processed > 0 && !statusData.completed))));
      } catch (err) {
        console.error("Failed to load book:", err);
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [bookId]);

  const handleGenerateAudio = () => {
    const shouldRetryFailed = audioStatus
      ? audioStatus.error > 0 && audioStatus.pending === 0
      : chapters.some((chapter) => chapter.status === "error") &&
        !chapters.some((chapter) => chapter.status === "pending");
    setRetryFailed(shouldRetryFailed);
    // Immediately show progress tracker and generation state for instant feedback
    setShowProgressTracker(true);
    setGenerationRunning(true);
    setStartRequestKey((current) => current + 1);
  };

  const handleStatusChange = useCallback(
    (status: AudioStatus) => {
      applyAudioStatus(status);
      setGenerationRunning(status.is_running);
      setShowProgressTracker((current) => {
        if (status.completed) return false;
        if (current) return true;
        return status.is_running || (status.processed > 0 && !status.completed);
      });
    },
    [applyAudioStatus]
  );

  const handleGenerationComplete = useCallback(
    (status: AudioStatus) => {
      applyAudioStatus(status);
      setGenerationRunning(false);
      setShowProgressTracker(false);
      setRetryFailed(false);
    },
    [applyAudioStatus]
  );

  const handleBack = () => {
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
      return;
    }
    router.push("/");
  };

  if (loading) {
    return (
      <div className="page-shell space-y-6 pb-24">
        <Skeleton className="h-[540px] rounded-[2.4rem] bg-card/80" />
        <Skeleton className="h-[320px] rounded-[2rem] bg-card/80" />
      </div>
    );
  }

  if (!book) {
    return (
      <div className="page-shell pb-24">
        <div className="surface-card rounded-[2rem] px-8 py-20 text-center">
          <p className="text-lg text-muted-foreground">Book not found.</p>
          <Link href="/" className="mt-4 inline-flex text-sm font-medium text-foreground underline underline-offset-4">
            Return home
          </Link>
        </div>
      </div>
    );
  }

  const readyCount = audioStatus?.ready ?? chapters.filter((chapter) => chapter.status === "ready").length;
  const pendingCount = audioStatus?.pending ?? chapters.filter((chapter) => chapter.status === "pending").length;
  const errorCount = audioStatus?.error ?? chapters.filter((chapter) => chapter.status === "error").length;
  const totalChapterCount = audioStatus?.total_chapters ?? chapters.length;
  const hasAudio = readyCount > 0;
  const canStartGeneration = audioStatus?.can_start ?? pendingCount > 0;
  const canRetryFailed = audioStatus?.can_retry_failed ?? errorCount > 0;
  const showGenerateBtn = !generationRunning && (canStartGeneration || canRetryFailed);
  const generateLabel = canRetryFailed && !canStartGeneration
    ? "Retry Failed Chapters"
    : hasAudio
      ? "Resume Generation"
      : "Generate Audio";

  return (
    <div className="space-y-12 pb-24">
      <div className="page-shell">
        <section className="hero-panel overflow-hidden">
          <div className="hero-orb left-[-6rem] top-[10rem] h-72 w-72 text-foreground/20" />
          <div className="hero-orb bottom-[-8rem] right-[-4rem] h-72 w-72 text-foreground/18" />

          <div className="relative px-4 py-6 sm:px-6 sm:py-8 md:px-10 lg:px-14 lg:py-12">
            <button
              type="button"
              onClick={handleBack}
              className="apple-link inline-flex items-center gap-2"
            >
              <ArrowLeft className="size-4" />
              <span>Back</span>
            </button>

            <div className="mt-6 grid gap-8 sm:mt-8 sm:gap-10 lg:grid-cols-[360px_1fr] lg:items-center">
              <div className="animate-float">
                <div className="surface-card overflow-hidden rounded-[2.3rem] p-3">
                  <div className="relative aspect-[3/4] overflow-hidden rounded-[1.8rem] border border-border/70 bg-gradient-to-br from-background via-muted/60 to-secondary/90">
                    {book.cover_image_url ? (
                      <img src={book.cover_image_url} alt={book.title} className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full flex-col justify-between p-7">
                        <span className="apple-pill w-fit">Audibuddy</span>
                        <div className="space-y-3">
                          <div className="flex size-14 items-center justify-center rounded-2xl border border-border/70 bg-background/60">
                            <BookOpen className="size-6 text-foreground" />
                          </div>
                          <div>
                            <p className="text-2xl font-semibold tracking-tight text-foreground">{book.title}</p>
                            <p className="mt-2 text-base text-muted-foreground">{book.author}</p>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="space-y-6 animate-fade-in-up">
                <div className="space-y-4">
                  <Badge variant="outline" className="rounded-full border-border/70 bg-background/60 px-3 py-1 text-[0.68rem] tracking-[0.22em] uppercase text-muted-foreground">
                    {book.genre}
                  </Badge>
                  <div>
                    <h1 className="section-heading text-4xl md:text-5xl lg:text-6xl">{book.title}</h1>
                    <p className="mt-3 text-lg text-muted-foreground">by {book.author}</p>
                  </div>
                  <p className="max-w-2xl text-base leading-7 text-muted-foreground">{book.description}</p>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="glass-panel rounded-[1.5rem] p-4">
                    <p className="section-kicker">Chapters</p>
                    <p className="mt-2 text-lg font-semibold text-foreground">{book.total_chapters}</p>
                  </div>
                  <div className="glass-panel rounded-[1.5rem] p-4">
                    <p className="section-kicker">Duration</p>
                    <p className="mt-2 text-lg font-semibold text-foreground">{formatDuration(book.total_duration_seconds)}</p>
                  </div>
                  <div className="glass-panel rounded-[1.5rem] p-4">
                    <p className="section-kicker">Audio Ready</p>
                    <p className="mt-2 text-lg font-semibold text-foreground">{readyCount}/{Math.max(totalChapterCount, 1)}</p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  {isAdmin && showGenerateBtn && (
                    <Button onClick={handleGenerateAudio} size="lg" className="h-11 rounded-full px-5">
                      {generateLabel}
                    </Button>
                  )}
                  {isAdmin && generationRunning && (
                    <Button disabled size="lg" className="h-11 rounded-full px-5">
                      <div className="size-4 rounded-full border-2 border-primary-foreground/30 border-t-primary-foreground animate-spin" />
                      <span>Generating</span>
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="lg"
                    className="h-11 rounded-full px-5"
                    onClick={() => setFavorited((current) => !current)}
                  >
                    <Heart className={`size-4 ${favorited ? "fill-current" : ""}`} />
                    <span>{favorited ? "Favorited" : "Favorite"}</span>
                  </Button>
                </div>

                {isAdmin && (
                  <div className="text-sm text-muted-foreground">
                    {errorCount > 0 && <span>{errorCount} failed.</span>}
                    {errorCount > 0 && pendingCount > 0 && <span> </span>}
                    {pendingCount > 0 && <span>{pendingCount} chapters still need audio.</span>}
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
      </div>

      <div className="page-shell space-y-10">
        {/* Quota assessment — shows before generation, admin only */}
        {isAdmin && !showProgressTracker && totalChapterCount > 0 && (
          <QuotaAssessment bookId={bookId} hidden={generationRunning} />
        )}

        {showProgressTracker && (
          <AudioProgressTracker
            bookId={bookId}
            startRequestKey={startRequestKey}
            retryFailed={retryFailed}
            onStatusChange={handleStatusChange}
            onComplete={handleGenerationComplete}
          />
        )}

        {!showProgressTracker && hasAudio && <AudioPlayer bookId={bookId} chapters={chapters} />}

        {!showProgressTracker && !hasAudio && totalChapterCount > 0 && (
          <div className="surface-card rounded-[2rem] p-6 text-center sm:p-8">
            <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
              {isAdmin ? "Ready for audio generation" : "Audio coming soon"}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {isAdmin
                ? 'Click "Generate Audio" above to start creating the audiobook.'
                : "The developer is working on generating audio for this book. Check back later."}
            </p>
          </div>
        )}

        {similar.length > 0 && (
          <BookRow
            title="You Might Also Like"
            books={similar}
            onBookDeleted={(deletedBookId) => {
              setSimilar((current) => current.filter((item) => item.id !== deletedBookId));
            }}
          />
        )}
      </div>
    </div>
  );
}
