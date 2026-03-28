"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, Info, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Book } from "@/lib/api";

export default function HeroBanner({ books }: { books: Book[] }) {
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (books.length <= 1) return;
    const timer = window.setInterval(() => {
      setCurrent((prev) => (prev + 1) % books.length);
    }, 6500);
    return () => window.clearInterval(timer);
  }, [books.length]);

  if (books.length === 0) return null;

  const book = books[current];

  return (
    <section className="page-shell pb-8">
      <div className="hero-panel min-h-[400px] sm:min-h-[500px] lg:min-h-[580px]">
        <div className="hero-orb left-[-8rem] top-[8rem] h-72 w-72 text-foreground/25" />
        <div className="hero-orb bottom-[-10rem] right-[-6rem] h-80 w-80 text-foreground/20" />

        <div className="relative grid min-h-[400px] gap-8 px-4 py-6 sm:min-h-[500px] sm:gap-10 sm:px-6 sm:py-8 md:px-10 md:py-10 lg:min-h-[580px] lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:gap-12 lg:px-14 lg:py-14">
          <div className="max-w-2xl space-y-7 animate-fade-in-up">
            <div className="space-y-3">
              <span className="apple-pill">Featured Listening</span>
              <h1 className="section-heading text-2xl sm:text-4xl lg:text-5xl xl:text-6xl">{book.title}</h1>
              <p className="max-w-xl text-base leading-7 text-muted-foreground md:text-lg">
                by {book.author}
                {book.description ? ` - ${book.description}` : ""}
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link href={`/book/${book.id}`}>
                <Button size="lg" className="h-11 rounded-full px-5">
                  <Play className="size-4 fill-current" />
                  <span>Listen Now</span>
                </Button>
              </Link>
              <Link href={`/book/${book.id}`}>
                <Button size="lg" variant="outline" className="h-11 rounded-full px-5">
                  <Info className="size-4" />
                  <span>More Info</span>
                </Button>
              </Link>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="glass-panel rounded-[1.5rem] p-4">
                <p className="section-kicker">Genre</p>
                <p className="mt-2 text-lg font-semibold text-foreground">{book.genre}</p>
              </div>
              <div className="glass-panel rounded-[1.5rem] p-4">
                <p className="section-kicker">Chapters</p>
                <p className="mt-2 text-lg font-semibold text-foreground">{book.total_chapters}</p>
              </div>
              <div className="glass-panel rounded-[1.5rem] p-4">
                <p className="section-kicker">Duration</p>
                <p className="mt-2 text-lg font-semibold text-foreground">
                  {book.total_duration_seconds > 0
                    ? `${Math.max(Math.round(book.total_duration_seconds / 60), 1)} min`
                    : "Preparing"}
                </p>
              </div>
            </div>
          </div>

          <div className="relative hidden items-center justify-center sm:flex lg:justify-end">
            <div className="animate-float relative w-full max-w-[380px]">
              <div className="absolute inset-6 rounded-[2.25rem] border border-white/40 dark:border-white/10" />
              <div className="surface-card overflow-hidden rounded-[2.6rem] p-3">
                <div className="relative aspect-[4/5] overflow-hidden rounded-[2rem] border border-border/70 bg-gradient-to-br from-background via-muted/60 to-secondary/90">
                  {book.cover_image_url ? (
                    <img src={book.cover_image_url} alt={book.title} className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full flex-col justify-between p-8">
                      <span className="apple-pill w-fit">Audibuddy</span>
                      <div className="space-y-3">
                        <p className="text-3xl font-semibold tracking-tight text-foreground">{book.title}</p>
                        <p className="text-base text-muted-foreground">{book.author}</p>
                      </div>
                    </div>
                  )}

                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-black/60 via-black/10 to-transparent dark:from-black/80" />
                  <div className="absolute inset-x-0 bottom-0 flex items-center justify-between px-5 pb-5 text-sm font-medium text-white/90">
                    <span>{book.genre}</span>
                    <span>{book.total_chapters} chapters</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {books.length > 1 && (
          <>
            <div className="absolute bottom-6 left-6 flex items-center gap-2 md:left-10">
              {books.map((_, index) => (
                <button
                  key={index}
                  type="button"
                  aria-label={`Show featured book ${index + 1}`}
                  onClick={() => setCurrent(index)}
                  className={`h-2.5 rounded-full transition-all duration-500 ${
                    index === current ? "w-10 bg-foreground" : "w-2.5 bg-foreground/25"
                  }`}
                />
              ))}
            </div>

            <div className="absolute bottom-5 right-6 flex items-center gap-2 md:right-10">
              <button
                type="button"
                aria-label="Previous featured book"
                onClick={() => setCurrent((current - 1 + books.length) % books.length)}
                className="flex size-11 items-center justify-center rounded-full border border-border/70 bg-card/75 text-foreground backdrop-blur-xl hover:bg-card/95 active:scale-95"
              >
                <ChevronLeft className="size-4" />
              </button>
              <button
                type="button"
                aria-label="Next featured book"
                onClick={() => setCurrent((current + 1) % books.length)}
                className="flex size-11 items-center justify-center rounded-full border border-border/70 bg-card/75 text-foreground backdrop-blur-xl hover:bg-card/95 active:scale-95"
              >
                <ChevronRight className="size-4" />
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
