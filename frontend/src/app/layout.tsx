import type { Metadata } from "next";
import Script from "next/script";

import Navbar from "@/components/layout/navbar";
import { AdminProvider } from "@/lib/admin-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Audibuddy",
  description: "Upload PDFs, auto-generate audiobooks, stream with an immersive listening experience.",
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    shortcut: "/icon.svg",
    apple: "/icon.svg",
  },
};

const themeScript = `
(() => {
  try {
    const storageKey = "audi-buddy-theme";
    const stored = window.localStorage.getItem(storageKey);
    const theme = stored === "light" || stored === "dark"
      ? stored
      : (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.dataset.theme = theme;
  } catch (error) {
    document.documentElement.classList.remove("dark");
    document.documentElement.dataset.theme = "light";
  }
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <Script id="theme-init" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen antialiased selection:bg-foreground/10 selection:text-foreground">
        <AdminProvider>
          <Navbar />
          <main className="relative min-h-screen pt-24 md:pt-28">{children}</main>
        </AdminProvider>
      </body>
    </html>
  );
}
