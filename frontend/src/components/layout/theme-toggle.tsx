"use client";

import { MoonStar, SunMedium } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "audi-buddy-theme";

type Theme = "light" | "dark";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  // Enable smooth theme transition, then remove after it completes
  root.classList.add("theme-transitioning");
  root.classList.toggle("dark", theme === "dark");
  root.dataset.theme = theme;
  window.localStorage.setItem(STORAGE_KEY, theme);
  // Remove the class after transition finishes so it doesn't affect normal perf
  setTimeout(() => root.classList.remove("theme-transitioning"), 200);
}

interface ThemeToggleProps {
  className?: string;
}

export default function ThemeToggle({ className }: ThemeToggleProps) {
  // Start with null to avoid any rendering until after mount (prevents hydration mismatch)
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    // Read actual theme from DOM after mount — this matches what the inline script set
    const isDark = document.documentElement.classList.contains("dark");
    setTheme(isDark ? "dark" : "light");
  }, []);

  // Don't render anything until we know the theme (prevents hydration mismatch)
  if (theme === null) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label="Toggle theme"
        className={cn("theme-toggle-button", className)}
        disabled
      >
        <span className="size-4" />
        <span>Theme</span>
      </Button>
    );
  }

  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-label={`Switch to ${nextTheme} mode`}
      className={cn("theme-toggle-button", className)}
      onClick={() => {
        const updatedTheme = theme === "dark" ? "light" : "dark";
        setTheme(updatedTheme);
        applyTheme(updatedTheme);
      }}
    >
      {theme === "dark" ? <SunMedium className="size-4" /> : <MoonStar className="size-4" />}
      <span>{nextTheme === "dark" ? "Dark Mode" : "Light Mode"}</span>
    </Button>
  );
}
