"use client";

import { useRef, type CSSProperties } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Book } from "@/lib/api";
import BookCard from "./book-card";

interface BookRowProps {
  title: string;
  books: Book[];
  onBookDeleted?: (bookId: string) => void;
}

export default function BookRow({ title, books, onBookDeleted }: BookRowProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  if (books.length === 0) return null;

  const scroll = (direction: "left" | "right") => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollBy({
      left: direction === "left" ? -460 : 460,
      behavior: "smooth",
    });
  };

  return (
    <section className="space-y-5 animate-fade-in-up">
      <div className="flex items-end justify-between gap-4">
        <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl md:text-3xl">{title}</h2>
      </div>

      <div className="group/row relative">
        <button
          type="button"
          onClick={() => scroll("left")}
          className="motion-interactive absolute left-0 top-[36%] z-10 hidden size-11 -translate-y-1/2 items-center justify-center rounded-full border border-border/70 bg-card/85 text-foreground backdrop-blur-xl opacity-0 shadow-sm group-hover/row:opacity-100 hover:bg-card lg:flex"
          aria-label={`Scroll ${title} left`}
        >
          <ChevronLeft className="size-5" />
        </button>

        <div
          ref={scrollRef}
          className="scrollbar-hide flex gap-3 overflow-x-auto pb-4 sm:gap-5"
          style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
        >
          {books.map((book, index) => (
            <div
              key={book.id}
              className="stagger-item w-[160px] shrink-0 sm:w-[208px]"
              style={{ "--stagger-index": index } as CSSProperties}
            >
              <BookCard book={book} onDeleted={onBookDeleted} />
            </div>
          ))}
        </div>

        <button
          type="button"
          onClick={() => scroll("right")}
          className="motion-interactive absolute right-0 top-[36%] z-10 hidden size-11 -translate-y-1/2 items-center justify-center rounded-full border border-border/70 bg-card/85 text-foreground backdrop-blur-xl opacity-0 shadow-sm group-hover/row:opacity-100 hover:bg-card lg:flex"
          aria-label={`Scroll ${title} right`}
        >
          <ChevronRight className="size-5" />
        </button>
      </div>
    </section>
  );
}
