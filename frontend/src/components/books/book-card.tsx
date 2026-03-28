"use client";

import { useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BookOpen, Camera, Clock, Edit3, MoreHorizontal, Tag, Trash2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useAdmin } from "@/lib/admin-context";
import { Book, deleteBook, updateBookMetadata } from "@/lib/api";

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const hrs = Math.floor(mins / 60);
  if (hrs > 0) return `${hrs}h ${mins % 60}m`;
  return `${mins}m`;
}

const GENRES = [
  "General", "Fantasy", "Science Fiction", "Romance", "Mystery", "Horror",
  "Non-Fiction", "Biography", "History", "Self-Help", "Business",
  "Technology", "Philosophy", "Poetry", "Children",
];

interface BookCardProps {
  book: Book;
  onDeleted?: (bookId: string) => void;
  onUpdated?: (book: Book) => void;
}

export default function BookCard({ book: initialBook, onDeleted, onUpdated }: BookCardProps) {
  const router = useRouter();
  const { isAdmin } = useAdmin();
  const [book, setBook] = useState(initialBook);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [removed, setRemoved] = useState(false);
  const [, startTransition] = useTransition();

  // Edit state
  const [editGenre, setEditGenre] = useState(book.genre);
  const [editCoverFile, setEditCoverFile] = useState<File | null>(null);
  const [editCoverPreview, setEditCoverPreview] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const coverInputRef = useRef<HTMLInputElement>(null);

  async function handleRemoveBook() {
    setIsDeleting(true);
    setDeleteError(null);

    try {
      await deleteBook(book.id);
      setRemoved(true);
      setConfirmOpen(false);
      onDeleted?.(book.id);
      startTransition(() => {
        router.refresh();
      });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Failed to remove the book.");
    } finally {
      setIsDeleting(false);
    }
  }

  function handleCoverChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setEditCoverFile(file);
    setEditCoverPreview(URL.createObjectURL(file));
  }

  function openEditDialog() {
    setEditGenre(book.genre);
    setEditCoverFile(null);
    setEditCoverPreview(null);
    setEditError(null);
    setEditOpen(true);
  }

  async function handleSaveMetadata() {
    setIsSaving(true);
    setEditError(null);

    try {
      const formData = new FormData();
      if (editGenre !== book.genre) {
        formData.append("genre", editGenre);
      }
      if (editCoverFile) {
        formData.append("cover_image", editCoverFile);
      }

      const updated = await updateBookMetadata(book.id, formData);
      setBook(updated);
      onUpdated?.(updated);
      setEditOpen(false);
      startTransition(() => {
        router.refresh();
      });
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "Failed to update book.");
    } finally {
      setIsSaving(false);
    }
  }

  if (removed) {
    return null;
  }

  return (
    <>
      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!isDeleting) {
            setConfirmOpen(open);
            if (!open) setDeleteError(null);
          }
        }}
      >
        <div className="group relative w-full min-w-0 sm:w-[208px] shrink-0">
          {/* Action buttons on hover (admin only) */}
          {isAdmin && <div className="absolute right-3 top-3 z-20 flex gap-1.5 opacity-0 transition duration-300 group-hover:opacity-100 group-focus-within:opacity-100 sm:right-4 sm:top-4">
            <button
              type="button"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); openEditDialog(); }}
              aria-label={`Edit ${book.title}`}
              className="flex size-8 items-center justify-center rounded-full border border-border/70 bg-background/90 text-foreground shadow-sm backdrop-blur-xl transition hover:bg-background sm:size-9"
            >
              <Edit3 className="size-3.5" />
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger
                aria-label={`Open actions for ${book.title}`}
                className="flex size-8 items-center justify-center rounded-full border border-border/70 bg-background/90 text-foreground shadow-sm backdrop-blur-xl transition hover:bg-background sm:size-9"
              >
                <MoreHorizontal className="size-3.5 sm:size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                sideOffset={8}
                className="w-44 rounded-2xl border border-border/70 bg-background/96 p-1.5 shadow-[var(--shadow-panel)] backdrop-blur-xl"
              >
                <DropdownMenuItem
                  variant="destructive"
                  onClick={() => {
                    setDeleteError(null);
                    setConfirmOpen(true);
                  }}
                >
                  <Trash2 className="size-4" />
                  <span>Remove This Book</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>}

          <Link href={`/book/${book.id}?autoplay=1`} className="block">
            <div className="surface-card interactive-surface overflow-hidden rounded-[1.5rem] p-1.5 sm:rounded-[2rem] sm:p-2">
              <div className="relative aspect-[3/4] overflow-hidden rounded-[1.2rem] border border-border/70 bg-gradient-to-br from-background via-muted/60 to-secondary/90 sm:rounded-[1.5rem]">
                {book.cover_image_url ? (
                  <img
                    src={book.cover_image_url}
                    alt={book.title}
                    className="h-full w-full object-cover transition duration-700 group-hover:scale-[1.04]"
                  />
                ) : (
                  <div className="flex h-full flex-col justify-between p-3 sm:p-5">
                    <div className="apple-pill w-fit text-[0.55rem] sm:text-xs">No cover</div>
                    <div className="space-y-2 sm:space-y-3">
                      <div className="flex size-10 items-center justify-center rounded-xl border border-border/70 bg-background/70 sm:size-12 sm:rounded-2xl">
                        <BookOpen className="size-4 text-foreground sm:size-5" />
                      </div>
                      <div>
                        <p className="line-clamp-3 text-sm font-semibold tracking-tight text-foreground sm:text-lg">
                          {book.title}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground sm:mt-2 sm:text-sm">{book.author}</p>
                      </div>
                    </div>
                  </div>
                )}

                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-black/55 via-black/15 to-transparent opacity-70 transition-opacity duration-500 group-hover:opacity-90 dark:from-black/75 sm:h-28" />

                <div className="absolute inset-x-0 bottom-0 flex items-center justify-between px-3 pb-3 text-[0.65rem] font-medium text-white/86 sm:px-4 sm:pb-4 sm:text-xs">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="size-3" />
                    {formatDuration(book.total_duration_seconds)}
                  </span>
                  <span>{book.total_chapters} ch</span>
                </div>
              </div>
            </div>

            <div className="mt-3 space-y-0.5 px-1 sm:mt-4 sm:space-y-1">
              <h3 className="truncate text-sm font-semibold tracking-tight text-foreground sm:text-[1rem]">{book.title}</h3>
              <p className="truncate text-xs text-muted-foreground sm:text-sm">{book.author}</p>
              <Badge variant="outline" className="mt-1.5 rounded-full border-border/70 bg-background/50 px-2 py-0.5 text-[0.6rem] tracking-[0.18em] uppercase text-muted-foreground sm:mt-2 sm:px-2.5 sm:py-1 sm:text-[0.65rem]">
                {book.genre}
              </Badge>
            </div>
          </Link>
        </div>

        <DialogContent
          className="mx-4 max-w-md rounded-[1.75rem] border border-border/70 bg-background/96 p-0 shadow-[var(--shadow-panel)] backdrop-blur-xl sm:mx-auto"
          showCloseButton={!isDeleting}
        >
          <DialogHeader className="px-6 pt-6">
            <DialogTitle>Remove this book?</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{book.title}</span> will be removed from the library,
              database, and stored files. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>

          {deleteError && (
            <div className="mx-6 rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {deleteError}
            </div>
          )}

          <DialogFooter className="rounded-b-[1.75rem] border-border/70 bg-muted/30 px-6 py-5">
            <div className="flex w-full flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={isDeleting} className="w-full sm:w-auto">
                Cancel
              </Button>
              <Button variant="destructive" onClick={handleRemoveBook} disabled={isDeleting} className="w-full sm:w-auto">
                {isDeleting ? "Removing..." : "Remove This Book"}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Metadata Dialog */}
      <Dialog open={editOpen} onOpenChange={(open) => { if (!isSaving) setEditOpen(open); }}>
        <DialogContent
          className="mx-4 max-w-md rounded-[1.75rem] border border-border/70 bg-background/96 p-0 shadow-[var(--shadow-panel)] backdrop-blur-xl sm:mx-auto"
          showCloseButton={!isSaving}
        >
          <DialogHeader className="px-6 pt-6">
            <DialogTitle>Edit Book</DialogTitle>
            <DialogDescription>
              Update genre or cover image for <span className="font-medium text-foreground">{book.title}</span>.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5 px-6 py-4">
            {/* Genre selector */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Tag className="size-3.5" />
                Genre
              </label>
              <select
                value={editGenre}
                onChange={(e) => setEditGenre(e.target.value)}
                className="apple-field h-11 w-full rounded-xl"
              >
                {GENRES.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </div>

            {/* Cover image */}
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Camera className="size-3.5" />
                Cover Image
              </label>
              <input
                ref={coverInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={handleCoverChange}
                className="hidden"
              />
              <div className="flex items-center gap-4">
                <div
                  onClick={() => coverInputRef.current?.click()}
                  className="apple-drop-zone flex h-28 w-20 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-xl"
                >
                  {editCoverPreview ? (
                    <img src={editCoverPreview} alt="New cover" className="h-full w-full object-cover" />
                  ) : book.cover_image_url ? (
                    <img src={book.cover_image_url} alt="Current cover" className="h-full w-full object-cover opacity-60" />
                  ) : (
                    <Camera className="size-5 text-muted-foreground" />
                  )}
                </div>
                <div className="flex-1 space-y-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => coverInputRef.current?.click()}
                    className="rounded-full"
                  >
                    Choose Image
                  </Button>
                  {editCoverFile && (
                    <button
                      type="button"
                      onClick={() => { setEditCoverFile(null); setEditCoverPreview(null); }}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      <X className="size-3" /> Remove
                    </button>
                  )}
                </div>
              </div>
            </div>

            {editError && (
              <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {editError}
              </div>
            )}
          </div>

          <DialogFooter className="rounded-b-[1.75rem] border-border/70 bg-muted/30 px-6 py-5">
            <div className="flex w-full flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={() => setEditOpen(false)} disabled={isSaving} className="w-full sm:w-auto">
                Cancel
              </Button>
              <Button onClick={handleSaveMetadata} disabled={isSaving || (editGenre === book.genre && !editCoverFile)} className="w-full sm:w-auto">
                {isSaving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
