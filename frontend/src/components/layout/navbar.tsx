"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Headphones, Menu, Search, Upload, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import ThemeToggle from "@/components/layout/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAdmin } from "@/lib/admin-context";
import { cn } from "@/lib/utils";

export default function Navbar() {
  const router = useRouter();
  const { isAdmin } = useAdmin();
  const [query, setQuery] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Close mobile menu on Escape key
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  // Close mobile menu on route change
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    router.push(`/search?q=${encodeURIComponent(query.trim())}`);
    setMobileOpen(false);
  };

  return (
    <nav className="fixed inset-x-0 top-0 z-50">
      <div className={cn("page-shell transition-all duration-250 ease-out", scrolled ? "pt-3" : "pt-4 md:pt-5")}>
        <div
          className={cn(
            "glass-nav flex items-center gap-4 px-4 py-3 md:px-6 transition-[border-radius] duration-250 ease-out",
            scrolled ? "rounded-full" : "rounded-[2rem]"
          )}
        >
          <Link href="/" className="flex items-center gap-3 shrink-0">
            <div className="flex size-10 items-center justify-center rounded-full border border-border/70 bg-background/70 backdrop-blur-xl">
              <Headphones className="size-4 text-foreground" />
            </div>
            <span className="hidden text-sm font-semibold tracking-tight text-foreground sm:block">Audibuddy</span>
          </Link>

          <div className="hidden lg:flex items-center gap-6 ml-4">
            <Link href="/" className="apple-link">
              Home
            </Link>
            <Link href="/library" className="apple-link">
              Library
            </Link>
            <Link href="/genre" className="apple-link">
              Genres
            </Link>
            {isAdmin && (
              <Link href="/upload" className="apple-link">
                Upload
              </Link>
            )}
          </div>

          <form onSubmit={handleSearch} className="hidden md:flex flex-1 justify-center">
            <div className="relative w-full max-w-md">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search books, authors, and genres"
                className="apple-input pl-11"
              />
            </div>
          </form>

          <div className="hidden md:flex items-center gap-2 ml-auto">
            <ThemeToggle />
            {isAdmin && (
              <Link href="/upload">
                <Button size="sm" className="h-10 rounded-full px-4">
                  <Upload className="size-4" />
                  <span>Upload</span>
                </Button>
              </Link>
            )}
          </div>

          <div className="ml-auto flex items-center gap-2 md:hidden">
            <button
              type="button"
              className="flex size-10 items-center justify-center rounded-full border border-border/80 bg-background/70 text-foreground backdrop-blur-xl hover:bg-background/90 active:scale-95"
              onClick={() => setMobileOpen((open) => !open)}
              aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"}
            >
              {mobileOpen ? <X className="size-4" /> : <Menu className="size-4" />}
            </button>
          </div>
        </div>

        {mobileOpen && (
          <>
            {/* Invisible backdrop — click outside to close mobile menu */}
            <div
              className="fixed inset-0 z-[-1] md:hidden"
              aria-hidden="true"
              onClick={closeMobile}
            />
            <div className="glass-panel mt-3 rounded-[2rem] p-4 md:hidden">
              <form onSubmit={handleSearch} className="mb-4">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search the library"
                    className="apple-input pl-11"
                  />
                </div>
              </form>

              <div className="grid gap-2">
                <Link href="/" className="apple-link rounded-2xl px-3 py-2" onClick={closeMobile}>
                  Home
                </Link>
                <Link href="/library" className="apple-link rounded-2xl px-3 py-2" onClick={closeMobile}>
                  Library
                </Link>
                <Link href="/genre" className="apple-link rounded-2xl px-3 py-2" onClick={closeMobile}>
                  Genres
                </Link>
                {isAdmin && (
                  <Link href="/upload" className="apple-link rounded-2xl px-3 py-2" onClick={closeMobile}>
                    Upload
                  </Link>
                )}
                <ThemeToggle className="justify-center" />
              </div>
            </div>
          </>
        )}
      </div>
    </nav>
  );
}
