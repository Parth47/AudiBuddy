"use client";

import { Suspense, useEffect, useState, type CSSProperties } from "react";
import { useSearchParams } from "next/navigation";
import { Search as SearchIcon } from "lucide-react";

import BookCard from "@/components/books/book-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Book, searchBooks } from "@/lib/api";

function SearchContent() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") || "";

  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<Book[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    if (!initialQuery) return;
    void handleSearch(initialQuery);
  }, [initialQuery]);

  async function handleSearch(value: string) {
    if (!value.trim()) return;
    setLoading(true);
    setSearched(true);

    try {
      setResults(await searchBooks(value.trim()));
    } catch (err) {
      console.error("Search failed:", err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-shell pb-24">
      <div className="animate-fade-in-up space-y-5">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Search</h1>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void handleSearch(query);
          }}
        >
          <div className="relative max-w-2xl">
            <SearchIcon className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground sm:left-5 sm:size-5" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Title, author, or genre"
              className="apple-input h-12 rounded-full pl-11 text-base sm:h-14 sm:pl-14 md:text-lg"
            />
          </div>
        </form>
      </div>

      <div className="mt-10">
        {loading ? (
          <div className="flex flex-wrap gap-5">
            {[1, 2, 3, 4].map((item) => (
              <Skeleton key={item} className="h-[356px] w-[208px] rounded-[2rem] bg-card/80" />
            ))}
          </div>
        ) : results.length > 0 ? (
          <>
            <p className="mb-4 text-sm text-muted-foreground">
              {results.length} result{results.length !== 1 ? "s" : ""}
            </p>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
              {results.map((book, index) => (
                <div
                  key={book.id}
                  className="stagger-item"
                  style={{ "--stagger-index": index } as CSSProperties}
                >
                  <BookCard
                    book={book}
                    onDeleted={(deletedBookId) => {
                      setResults((current) => current.filter((item) => item.id !== deletedBookId));
                    }}
                  />
                </div>
              ))}
            </div>
          </>
        ) : searched ? (
          <div className="surface-card rounded-[2rem] px-8 py-16 text-center">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">No books found.</h2>
            <p className="mt-3 text-muted-foreground">Try another search term or upload a new book to expand your library.</p>
          </div>
        ) : (
          <div className="surface-card rounded-[2rem] px-8 py-16 text-center">
            <p className="text-muted-foreground">Enter a search term to begin.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense
      fallback={
        <div className="page-shell pb-24">
          <Skeleton className="h-[320px] rounded-[2.4rem] bg-card/80" />
        </div>
      }
    >
      <SearchContent />
    </Suspense>
  );
}
