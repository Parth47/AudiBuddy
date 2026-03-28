"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Loader2,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  SkipBack,
  SkipForward,
  Volume1,
  Volume2,
  VolumeX,
} from "lucide-react";

import { Slider } from "@/components/ui/slider";
import { Chapter, getAudioStream } from "@/lib/api";

interface AudioPlayerProps {
  bookId: string;
  chapters: Chapter[];
  initialChapter?: number;
  initialTime?: number;
}

const PLAYBACK_SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] as const;
const SKIP_SECONDS = 30;

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export default function AudioPlayer({
  bookId,
  chapters,
  initialChapter = 1,
  initialTime = 0,
}: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentChapter, setCurrentChapter] = useState(initialChapter);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(80);
  const [muted, setMuted] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);

  const readyChapters = chapters.filter((chapter) => chapter.status === "ready");
  const currentChapterData = chapters.find((chapter) => chapter.chapter_number === currentChapter);

  const loadChapter = useCallback(
    async (chapterNumber: number, startAt?: number) => {
      setLoading(true);
      setError(null);

      try {
        const info = await getAudioStream(bookId, chapterNumber);
        setAudioUrl(info.audio_url);
        setCurrentChapter(chapterNumber);

        window.setTimeout(() => {
          const audio = audioRef.current;
          if (!audio) return;
          if (startAt && startAt > 0) audio.currentTime = startAt;
          audio.playbackRate = playbackSpeed;
          audio.play().catch(() => {});
          setIsPlaying(true);
        }, 300);
      } catch {
        setError("Audio is not available for this chapter yet.");
      } finally {
        setLoading(false);
      }
    },
    [bookId, playbackSpeed]
  );

  useEffect(() => {
    if (readyChapters.length === 0) return;
    const selected = readyChapters.find((chapter) => chapter.chapter_number === initialChapter);
    const startChapter = selected ? initialChapter : readyChapters[0].chapter_number;
    void loadChapter(startChapter, initialTime);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!audioRef.current) return;
    audioRef.current.volume = muted ? 0 : volume / 100;
  }, [muted, volume]);

  // Apply playback speed when it changes
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackSpeed;
    }
  }, [playbackSpeed]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      audio.play().catch(() => {});
    }
    setIsPlaying((playing) => !playing);
  };

  const seek = (value: number | readonly number[]) => {
    const nextTime = typeof value === "number" ? value : value[0];
    if (!audioRef.current) return;
    audioRef.current.currentTime = nextTime;
    setCurrentTime(nextTime);
  };

  const skipForward = () => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = Math.min(
      audioRef.current.duration || 0,
      audioRef.current.currentTime + SKIP_SECONDS
    );
  };

  const skipBackward = () => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = Math.max(0, audioRef.current.currentTime - SKIP_SECONDS);
  };

  const nextChapter = () => {
    const index = readyChapters.findIndex((chapter) => chapter.chapter_number === currentChapter);
    if (index < readyChapters.length - 1) {
      void loadChapter(readyChapters[index + 1].chapter_number);
    }
  };

  const prevChapter = () => {
    const index = readyChapters.findIndex((chapter) => chapter.chapter_number === currentChapter);
    if (index > 0) {
      void loadChapter(readyChapters[index - 1].chapter_number);
    }
  };

  const cycleSpeed = () => {
    const currentIndex = PLAYBACK_SPEEDS.indexOf(playbackSpeed as typeof PLAYBACK_SPEEDS[number]);
    const nextIndex = (currentIndex + 1) % PLAYBACK_SPEEDS.length;
    setPlaybackSpeed(PLAYBACK_SPEEDS[nextIndex]);
  };

  return (
    <div className="surface-card rounded-[2rem] p-5 sm:p-6 md:p-8">
      <audio
        ref={audioRef}
        src={audioUrl || undefined}
        onTimeUpdate={() => setCurrentTime(audioRef.current?.currentTime || 0)}
        onDurationChange={() => setDuration(audioRef.current?.duration || 0)}
        onEnded={nextChapter}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
      />

      <div className="space-y-5 sm:space-y-6">
        <div className="text-center">
          <p className="section-kicker mb-2">Now Playing</p>
          <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
            {currentChapterData?.title || "Loading..."}
          </h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Chapter {currentChapter} of {chapters.length}
          </p>
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </div>

        {/* Progress bar */}
        <div className="space-y-2">
          <Slider value={[currentTime]} max={duration || 100} step={1} onValueChange={seek} className="cursor-pointer" />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>

        {/* Main controls */}
        <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={prevChapter}
            className="flex size-10 items-center justify-center rounded-full border border-border/80 bg-background/60 text-foreground hover:bg-background/90 active:scale-95 sm:size-11"
            title="Previous chapter"
          >
            <SkipBack className="size-4" />
          </button>
          <button
            type="button"
            onClick={skipBackward}
            className="flex size-10 items-center justify-center rounded-full border border-border/80 bg-background/60 text-foreground hover:bg-background/90 active:scale-95 sm:size-11"
            title="Back 30 seconds"
          >
            <RotateCcw className="size-4" />
            <span className="absolute text-[8px] font-bold mt-0.5">30</span>
          </button>
          <button
            type="button"
            onClick={togglePlay}
            disabled={loading || !audioUrl}
            className="flex size-12 items-center justify-center rounded-full bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95 disabled:opacity-60 disabled:active:scale-100 sm:size-14"
            title={isPlaying ? "Pause" : "Play"}
          >
            {loading ? (
              <Loader2 className="size-5 animate-spin" />
            ) : isPlaying ? (
              <Pause className="size-5 fill-current" />
            ) : (
              <Play className="size-5 fill-current ml-0.5" />
            )}
          </button>
          <button
            type="button"
            onClick={skipForward}
            className="flex size-10 items-center justify-center rounded-full border border-border/80 bg-background/60 text-foreground hover:bg-background/90 active:scale-95 sm:size-11"
            title="Forward 30 seconds"
          >
            <RotateCw className="size-4" />
            <span className="absolute text-[8px] font-bold mt-0.5">30</span>
          </button>
          <button
            type="button"
            onClick={nextChapter}
            className="flex size-10 items-center justify-center rounded-full border border-border/80 bg-background/60 text-foreground hover:bg-background/90 active:scale-95 sm:size-11"
            title="Next chapter"
          >
            <SkipForward className="size-4" />
          </button>
        </div>

        {/* Speed + Volume row */}
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-center sm:gap-6">
          {/* Playback speed */}
          <button
            type="button"
            onClick={cycleSpeed}
            className="flex h-9 items-center justify-center rounded-full border border-border/80 bg-background/60 px-4 text-sm font-semibold text-foreground hover:bg-background/90 active:scale-95 transition-all"
            title="Change playback speed"
          >
            {playbackSpeed}x
          </button>

          {/* Volume */}
          <div className="flex w-full max-w-[220px] items-center gap-2.5 sm:w-auto sm:max-w-none">
            <button
              type="button"
              onClick={() => setMuted((current) => !current)}
              className="shrink-0 rounded-full p-1.5 text-muted-foreground hover:bg-background/80 hover:text-foreground transition-colors"
              title={muted ? "Unmute" : "Mute"}
            >
              {muted || volume === 0 ? (
                <VolumeX className="size-[18px]" />
              ) : volume < 50 ? (
                <Volume1 className="size-[18px]" />
              ) : (
                <Volume2 className="size-[18px]" />
              )}
            </button>
            <div className="relative flex w-28 items-center sm:w-36">
              <Slider
                value={[muted ? 0 : volume]}
                max={100}
                step={1}
                onValueChange={(value) => {
                  const nextVolume = typeof value === "number" ? value : value[0];
                  setVolume(nextVolume);
                  if (nextVolume > 0) setMuted(false);
                }}
                className="w-full cursor-pointer"
              />
            </div>
            <span className="min-w-[2ch] shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
              {muted ? 0 : volume}
            </span>
          </div>
        </div>

        {/* Chapter list */}
        <div className="border-t border-border/70 pt-5">
          <p className="mb-3 text-sm font-medium text-foreground">Chapters</p>
          <div className="max-h-56 space-y-2 overflow-y-auto pr-2 scrollbar-thin">
            {chapters.map((chapter) => (
              <button
                key={chapter.id}
                type="button"
                onClick={() => chapter.status === "ready" && void loadChapter(chapter.chapter_number)}
                disabled={chapter.status !== "ready"}
                className={`flex w-full items-center justify-between rounded-[1.2rem] border px-3 py-2.5 text-left text-sm transition sm:px-4 sm:py-3 ${
                  chapter.chapter_number === currentChapter
                    ? "border-border/80 bg-foreground text-background"
                    : chapter.status === "ready"
                      ? "border-border/70 bg-background/55 text-foreground hover:bg-card/80"
                      : "border-border/50 bg-muted/50 text-muted-foreground"
                }`}
              >
                <span className="truncate">
                  {chapter.chapter_number}. {chapter.title}
                </span>
                <span className={`ml-3 shrink-0 text-xs ${chapter.chapter_number === currentChapter ? "text-background/80" : "text-muted-foreground"}`}>
                  {chapter.status === "ready" ? formatTime(chapter.duration_seconds) : chapter.status}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
