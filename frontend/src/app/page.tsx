"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";

import BookRow from "@/components/books/book-row";
import HeroBanner from "@/components/books/hero-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { Book, getBooksByGenre, getFeaturedBooks, getGenres, getRecentBooks } from "@/lib/api";

interface HomeData {
  featured: Book[];
  recent: Book[];
  genreRows: { genre: string; books: Book[] }[];
  loadError: boolean;
}

export default function HomePage() {
  const [data, setData] = useState<HomeData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [featured, recent, genresData] = await Promise.all([
          getFeaturedBooks(),
          getRecentBooks(),
          getGenres(),
        ]);

        if (cancelled) return;

        // Fetch all genres in parallel
        const genreRows = (
          await Promise.all(
            genresData.genres.map(async (genre) => ({
              genre,
              books: await getBooksByGenre(genre),
            }))
          )
        ).filter(({ books }) => books.length > 0);

        if (cancelled) return;

        setData({ featured, recent, genreRows, loadError: false });
      } catch (error) {
        console.error("Failed to load homepage:", error);
        if (!cancelled) {
          setData({ featured: [], recent: [], genreRows: [], loadError: true });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="space-y-16 pb-24">
        <section className="page-shell pb-8">
          <Skeleton className="h-[420px] rounded-[2.4rem] bg-card/80" />
        </section>
        <div className="page-shell space-y-14">
          <Skeleton className="h-24 rounded-[2rem] bg-card/80" />
          <div className="flex gap-5">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-[320px] w-[208px] shrink-0 rounded-[2rem] bg-card/80" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  const { featured, recent, genreRows, loadError } = data!;
  const hasLibrary = recent.length > 0;

  return (
    <div className="space-y-16 pb-24">
      {featured.length > 0 ? (
        <HeroBanner books={featured} />
      ) : (
        <section className="page-shell pb-8">
          <div className="hero-panel min-h-[420px] px-6 py-10 md:px-10 md:py-12 lg:px-14">
            <div className="hero-orb left-[-7rem] top-[3rem] h-64 w-64 text-foreground/20" />
            <div className="hero-orb bottom-[-8rem] right-[-5rem] h-72 w-72 text-foreground/15" />
            <div className="relative flex min-h-[340px] max-w-3xl flex-col justify-center gap-7 animate-fade-in-up">
              <span className="apple-pill w-fit">{loadError ? "Offline" : "Audibuddy"}</span>
              <div className="space-y-3">
                <h1 className="section-heading text-3xl sm:text-4xl lg:text-5xl">
                  {loadError ? "Could not connect to the server." : "Your audiobook library starts here."}
                </h1>
                <p className="max-w-xl text-sm leading-6 text-muted-foreground md:text-base">
                  {loadError
                    ? "Check that the backend is running, then refresh."
                    : "Upload a PDF and it stays in your library."}
                </p>
              </div>
              <Link href="/upload" className="inline-flex">
                <span className="inline-flex items-center rounded-full bg-primary px-5 py-3 text-sm font-medium text-primary-foreground">
                  {loadError ? "Upload" : "Upload Your First Book"}
                </span>
              </Link>
            </div>
          </div>
        </section>
      )}

      <div className="page-shell space-y-14">
        <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div className="space-y-3 animate-fade-in-up">
            <p className="section-kicker">{hasLibrary ? "Your Library" : loadError ? "Connection Issue" : "Get Started"}</p>
            <h2 className="section-heading text-2xl sm:text-3xl md:text-[3.6rem]">
              {hasLibrary
                ? "Continue where you left off."
                : loadError
                  ? "Could not load your library."
                  : "Upload a PDF to begin."}
            </h2>
          </div>
          <div className="flex flex-col items-start gap-3 md:items-end">
            <Link href="/upload" className="inline-flex animate-fade-in-up">
              <span className="inline-flex items-center rounded-full border border-border/70 bg-background/80 px-5 py-3 text-sm font-medium text-foreground backdrop-blur-xl">
                {hasLibrary ? "Upload Another" : "Upload"}
              </span>
            </Link>
          </div>
        </div>

        {hasLibrary && (
          <div className="stagger-item" style={{ "--stagger-index": 0 } as CSSProperties}>
            <BookRow title="Recently Added" books={recent} />
          </div>
        )}

        {genreRows.map(({ genre, books }, index) => (
          <div key={genre} className="stagger-item" style={{ "--stagger-index": index + 1 } as CSSProperties}>
            <BookRow title={genre} books={books} />
          </div>
        ))}

        {loadError && (
          <div className="surface-card rounded-[2rem] p-8 text-center animate-fade-in-up sm:rounded-[2.4rem] sm:p-10">
            <h3 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">Could not load books</h3>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
              Check that the backend is running on <span className="font-medium text-foreground">localhost:8000</span>.
            </p>
          </div>
        )}

        {!loadError && !hasLibrary && (
          <div className="surface-card rounded-[2rem] p-8 text-center animate-fade-in-up sm:rounded-[2.4rem] sm:p-10">
            <h3 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">No books yet</h3>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
              Upload a PDF to start building your audiobook library.
            </p>
            <Link href="/upload" className="mt-5 inline-flex">
              <span className="inline-flex items-center rounded-full bg-primary px-5 py-3 text-sm font-medium text-primary-foreground">
                Upload Your First Book
              </span>
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
