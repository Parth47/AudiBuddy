"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { BookOpen, Library as LibraryIcon } from "lucide-react";

import BookCard from "@/components/books/book-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Book, getBooks, getGenres } from "@/lib/api";

interface GenreGroup {
  genre: string;
  books: Book[];
}

export default function LibraryPage() {
  const [genreGroups, setGenreGroups] = useState<GenreGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [{ books }, genresData] = await Promise.all([
          getBooks(),
          getGenres(),
        ]);

        if (cancelled) return;

        const groupMap = new Map<string, Book[]>();
        for (const genre of genresData.genres) {
          groupMap.set(genre, []);
        }
        for (const book of books) {
          const genre = book.genre || "General";
          if (!groupMap.has(genre)) {
            groupMap.set(genre, []);
          }
          groupMap.get(genre)!.push(book);
        }

        const groups: GenreGroup[] = [];
        for (const [genre, genreBooks] of groupMap) {
          if (genreBooks.length > 0) {
            groups.push({ genre, books: genreBooks });
          }
        }

        groups.sort((a, b) => b.books.length - a.books.length);

        setGenreGroups(groups);
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => { cancelled = true; };
  }, []);

  const handleBookDeleted = (bookId: string) => {
    setGenreGroups((prev) =>
      prev
        .map((group) => ({
          ...group,
          books: group.books.filter((b) => b.id !== bookId),
        }))
        .filter((group) => group.books.length > 0)
    );
  };

  if (loading) {
    return (
      <div className="page-shell space-y-10 pb-24">
        <Skeleton className="h-20 rounded-[2rem] bg-card/80" />
        <div className="space-y-8">
          {[1, 2, 3].map((i) => (
            <div key={i} className="space-y-4">
              <Skeleton className="h-8 w-48 rounded-xl bg-card/80" />
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
                {[1, 2, 3, 4].map((j) => (
                  <Skeleton key={j} className="aspect-[3/5] rounded-[2rem] bg-card/80" />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const totalBooks = genreGroups.reduce((sum, g) => sum + g.books.length, 0);

  return (
    <div className="page-shell space-y-10 pb-24">
      <div className="animate-fade-in-up">
        <div className="flex items-center gap-4">
          <div className="flex size-12 items-center justify-center rounded-2xl border border-border/70 bg-card/70 backdrop-blur-xl">
            <LibraryIcon className="size-5 text-foreground" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Library</h1>
            <p className="text-sm text-muted-foreground">
              {totalBooks} {totalBooks === 1 ? "book" : "books"} across {genreGroups.length} {genreGroups.length === 1 ? "genre" : "genres"}
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="surface-card rounded-[2rem] p-8 text-center animate-fade-in-up">
          <p className="text-lg font-semibold text-foreground">Could not load your library.</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Check that the backend is running on <span className="font-medium text-foreground">http://localhost:8000</span>.
          </p>
        </div>
      )}

      {!error && genreGroups.length === 0 && (
        <div className="surface-card rounded-[2rem] p-10 text-center animate-fade-in-up">
          <div className="mx-auto flex size-16 items-center justify-center rounded-2xl border border-border/70 bg-background/60">
            <BookOpen className="size-7 text-muted-foreground" />
          </div>
          <h2 className="mt-5 text-xl font-semibold text-foreground">Your library is empty</h2>
          <p className="mt-2 text-sm text-muted-foreground">Upload your first PDF to start building your audiobook collection.</p>
          <Link href="/upload" className="mt-6 inline-flex">
            <span className="inline-flex items-center rounded-full bg-primary px-5 py-3 text-sm font-medium text-primary-foreground">
              Upload a Book
            </span>
          </Link>
        </div>
      )}

      {genreGroups.map((group, groupIndex) => (
        <section
          key={group.genre}
          className="stagger-item space-y-4"
          style={{ "--stagger-index": groupIndex } as CSSProperties}
        >
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-semibold tracking-tight text-foreground">{group.genre}</h2>
            <span className="rounded-full border border-border/70 bg-card/50 px-2.5 py-0.5 text-xs text-muted-foreground">
              {group.books.length}
            </span>
          </div>

          <div className="relative">
            {/* Bookshelf visual */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {group.books.map((book, index) => (
                <div
                  key={book.id}
                  className="stagger-item w-full"
                  style={{ "--stagger-index": index } as CSSProperties}
                >
                  <BookCard book={book} onDeleted={handleBookDeleted} />
                </div>
              ))}
            </div>
            {/* Shelf line */}
            <div className="mt-2 h-1.5 rounded-full bg-gradient-to-r from-border/50 via-border/80 to-border/50" />
            <div className="h-1 rounded-b-full bg-gradient-to-b from-border/30 to-transparent" />
          </div>
        </section>
      ))}
    </div>
  );
}
