"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { getGenres } from "@/lib/api";

const genreTones = [
  "from-zinc-100 via-white to-zinc-200 dark:from-zinc-900 dark:via-zinc-950 dark:to-zinc-800",
  "from-stone-100 via-zinc-50 to-stone-200 dark:from-stone-900 dark:via-zinc-950 dark:to-stone-800",
  "from-slate-100 via-white to-slate-200 dark:from-slate-900 dark:via-zinc-950 dark:to-slate-800",
  "from-neutral-100 via-white to-neutral-200 dark:from-neutral-900 dark:via-zinc-950 dark:to-neutral-800",
];

function getTone(genre: string): string {
  let hash = 0;
  for (let index = 0; index < genre.length; index += 1) {
    hash = genre.charCodeAt(index) + ((hash << 5) - hash);
  }
  return genreTones[Math.abs(hash) % genreTones.length];
}

export default function GenrePage() {
  const [genres, setGenres] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const data = await getGenres();
        setGenres(data.genres);
      } catch (err) {
        console.error("Failed to load genres:", err);
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  return (
    <div className="page-shell pb-24 space-y-10">
      <div className="animate-fade-in-up">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Genres</h1>
        <p className="mt-1 text-sm text-muted-foreground">Browse your library by category.</p>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((item) => (
            <Skeleton key={item} className="h-40 rounded-[2rem] bg-card/80" />
          ))}
        </div>
      ) : genres.length > 0 ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {genres.map((genre, index) => (
            <Link
              key={genre}
              href={`/search?q=${encodeURIComponent(genre)}`}
              className="motion-interactive stagger-item group relative overflow-hidden rounded-[2rem] border border-border/70 p-6 shadow-[var(--shadow-panel)] hover:-translate-y-1"
              style={{ "--stagger-index": index } as CSSProperties}
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${getTone(genre)}`} />
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.55),transparent_38%)] dark:bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.08),transparent_38%)]" />
              <div className="relative flex h-28 flex-col justify-between">
                <div className="flex justify-between">
                  <span className="apple-pill">Genre</span>
                  <ArrowUpRight className="size-5 text-foreground transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </div>
                <h2 className="text-2xl font-semibold tracking-tight text-foreground">{genre}</h2>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="surface-card rounded-[2rem] px-8 py-16 text-center">
          <p className="text-muted-foreground">No genres yet. Upload some books to start shaping the catalog.</p>
        </div>
      )}
    </div>
  );
}
