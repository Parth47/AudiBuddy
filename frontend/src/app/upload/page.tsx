"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, AlertTriangle, CheckCircle, FileText, ImageIcon, Loader2, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAdmin } from "@/lib/admin-context";
import { retryWithFallback, uploadBook, UploadLLMError } from "@/lib/api";

const genres = [
  "General", "Fantasy", "Science Fiction", "Romance", "Mystery", "Horror",
  "Non-Fiction", "Biography", "History", "Self-Help", "Business",
  "Technology", "Philosophy", "Poetry", "Children",
];

export default function UploadPage() {
  const router = useRouter();
  const { isAdmin, loading: adminLoading } = useAdmin();
  const fileRef = useRef<HTMLInputElement>(null);
  const coverRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [genre, setGenre] = useState("General");
  const [description, setDescription] = useState("");
  const [uploading, setUploading] = useState(false);
  const [step, setStep] = useState<"form" | "processing" | "done" | "error" | "llm_failed">("form");
  const [error, setError] = useState("");
  const [bookId, setBookId] = useState("");
  const [retrying, setRetrying] = useState(false);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = e.target.files?.[0];
    if (!nextFile) return;
    setFile(nextFile);
    if (!title) {
      setTitle(nextFile.name.replace(".pdf", "").replace(/[_-]/g, " "));
    }
  };

  const handleCoverChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = e.target.files?.[0];
    if (!nextFile) return;
    setCoverFile(nextFile);
    setCoverPreview(URL.createObjectURL(nextFile));
  };

  const removeCover = () => {
    setCoverFile(null);
    if (coverPreview) {
      URL.revokeObjectURL(coverPreview);
      setCoverPreview(null);
    }
    if (coverRef.current) coverRef.current.value = "";
  };

  const resetForm = () => {
    setStep("form");
    setFile(null);
    removeCover();
    setTitle("");
    setAuthor("");
    setDescription("");
    setGenre("General");
    setError("");
    setBookId("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !title) return;

    setUploading(true);
    setStep("processing");
    setError("");

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", title);
      formData.append("author", author || "Unknown");
      formData.append("genre", genre);
      formData.append("description", description);
      if (coverFile) {
        formData.append("cover_image", coverFile);
      }

      const book = await uploadBook(formData);
      setBookId(book.id);
      setStep("done");
    } catch (err) {
      if (err instanceof UploadLLMError) {
        setBookId(err.data.book_id);
        setError(err.data.message);
        setStep("llm_failed");
      } else {
        setError(err instanceof Error ? err.message : "Upload failed");
        setStep("error");
      }
    } finally {
      setUploading(false);
    }
  };

  const handleRetryWithFallback = async () => {
    if (!bookId) return;
    setRetrying(true);
    setError("");

    try {
      const book = await retryWithFallback(bookId);
      setBookId(book.id);
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fallback processing failed");
      setStep("error");
    } finally {
      setRetrying(false);
    }
  };

  if (!adminLoading && !isAdmin) {
    return (
      <div className="page-shell pb-24">
        <div className="mx-auto max-w-lg animate-fade-in-up">
          <div className="surface-card rounded-[2rem] p-8 text-center sm:rounded-[2.4rem] sm:p-12">
            <div className="mx-auto mb-5 flex size-16 items-center justify-center rounded-full border border-border/70 bg-muted/40">
              <Upload className="size-6 text-muted-foreground" />
            </div>
            <h1 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">Developer Only</h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Uploading new books is only available for the developer. Browse the existing library to listen to audiobooks.
            </p>
            <Button onClick={() => router.push("/library")} className="mt-6 h-10 rounded-full px-5 sm:h-11">
              Browse Library
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page-shell pb-24">
      <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr] lg:gap-8">
        <div className="space-y-6 animate-fade-in-up">
          <div className="surface-card rounded-[2rem] p-6 sm:rounded-[2.4rem] sm:p-8 md:p-10">
            <p className="section-kicker">Upload</p>
            <h1 className="section-heading mt-3 text-2xl sm:text-3xl md:text-4xl">Add a book to your library.</h1>
            <p className="section-copy mt-3">
              Upload a PDF and we will extract chapters and prepare it for audio generation.
            </p>
          </div>

          <div className="surface-card rounded-[1.5rem] p-5 sm:rounded-[2rem] sm:p-6">
            <p className="section-kicker">Tips</p>
            <ul className="mt-3 space-y-2 text-sm leading-6 text-muted-foreground">
              <li>Use a clean PDF with readable chapter headings for the best audio segmentation.</li>
              <li>Optional cover art will be used across cards and the detail page.</li>
            </ul>
          </div>
        </div>

        <div className="surface-card rounded-[2rem] p-5 sm:rounded-[2.4rem] sm:p-6 md:p-8 animate-fade-in-up">
          {step === "form" && (
            <form onSubmit={handleSubmit} className="space-y-5 sm:space-y-6">
              <div>
                <label className="mb-2 block text-sm font-medium text-foreground sm:mb-3">PDF File</label>
                <div onClick={() => fileRef.current?.click()} className="apple-drop-zone cursor-pointer p-6 text-center sm:p-8 md:p-10">
                  <input ref={fileRef} type="file" accept=".pdf" onChange={handleFileChange} className="hidden" />
                  {file ? (
                    <div className="flex items-center justify-center gap-3 sm:gap-4">
                      <div className="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground sm:size-14 sm:rounded-2xl">
                        <FileText className="size-5 sm:size-6" />
                      </div>
                      <div className="text-left">
                        <p className="text-sm font-semibold text-foreground sm:text-base">{file.name}</p>
                        <p className="text-xs text-muted-foreground sm:text-sm">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2 sm:space-y-3">
                      <div className="mx-auto flex size-12 items-center justify-center rounded-xl border border-border/80 bg-background/60 sm:size-14 sm:rounded-2xl">
                        <Upload className="size-5 text-foreground sm:size-6" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-foreground sm:text-base">Choose a PDF</p>
                        <p className="mt-1 text-xs text-muted-foreground sm:text-sm">Click to browse or drag and drop.</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-foreground sm:mb-3">Cover Image</label>
                <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
                  <div
                    onClick={() => coverRef.current?.click()}
                    className="apple-drop-zone flex h-36 w-full shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-[1.5rem] sm:h-44 sm:w-32 sm:rounded-[1.8rem]"
                  >
                    <input
                      ref={coverRef}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      onChange={handleCoverChange}
                      className="hidden"
                    />
                    {coverPreview ? (
                      <img src={coverPreview} alt="Cover preview" className="h-full w-full object-cover" />
                    ) : (
                      <div className="space-y-2 text-center">
                        <ImageIcon className="mx-auto size-6 text-muted-foreground" />
                        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Add art</p>
                      </div>
                    )}
                  </div>

                  <div className="flex-1 space-y-2 sm:space-y-3">
                    <p className="text-sm leading-6 text-muted-foreground">
                      Optional. Recommended: 400 x 600 JPG, PNG, or WebP.
                    </p>
                    {coverFile && (
                      <button
                        type="button"
                        onClick={removeCover}
                        className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground"
                      >
                        <X className="size-4" />
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2 sm:gap-5">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Title</label>
                  <Input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Book title"
                    required
                    className="apple-field h-11 rounded-xl sm:h-12 sm:rounded-2xl"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Author</label>
                  <Input
                    value={author}
                    onChange={(e) => setAuthor(e.target.value)}
                    placeholder="Author name"
                    className="apple-field h-11 rounded-xl sm:h-12 sm:rounded-2xl"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Genre</label>
                <select value={genre} onChange={(e) => setGenre(e.target.value)} className="apple-field h-11 w-full rounded-xl sm:h-12 sm:rounded-2xl">
                  {genres.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Description</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Brief description (optional)"
                  rows={3}
                  className="apple-field w-full rounded-xl sm:rounded-[1.5rem]"
                />
              </div>

              <Button type="submit" disabled={!file || !title || uploading} className="h-11 w-full rounded-full text-sm sm:h-12">
                <Upload className="size-4" />
                <span>Upload and Process</span>
              </Button>
            </form>
          )}

          {step === "processing" && (
            <div className="flex min-h-[400px] flex-col items-center justify-center space-y-5 text-center sm:min-h-[480px]">
              <div className="flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground sm:size-16">
                <Loader2 className="size-6 animate-spin sm:size-7" />
              </div>
              <div>
                <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">Processing your book</h2>
                <p className="mt-2 max-w-md text-sm text-muted-foreground sm:mt-3">
                  Extracting text and detecting chapters. This may take a moment for larger books.
                </p>
              </div>
            </div>
          )}

          {step === "done" && (
            <div className="flex min-h-[400px] flex-col items-center justify-center space-y-5 text-center sm:min-h-[480px]">
              <div className="flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground sm:size-16">
                <CheckCircle className="size-6 sm:size-7" />
              </div>
              <div>
                <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">Upload complete</h2>
                <p className="mt-2 max-w-md text-sm text-muted-foreground sm:mt-3">
                  Open the book page to generate audio.
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button onClick={() => router.push(`/book/${bookId}`)} className="h-10 rounded-full px-5 sm:h-11">
                  Open Book
                </Button>
                <Button variant="outline" onClick={resetForm} className="h-10 rounded-full px-5 sm:h-11">
                  Upload Another
                </Button>
              </div>
            </div>
          )}

          {step === "llm_failed" && (
            <div className="flex min-h-[400px] flex-col items-center justify-center space-y-5 text-center sm:min-h-[480px]">
              <div className="flex size-14 items-center justify-center rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400 sm:size-16">
                <AlertTriangle className="size-6 sm:size-7" />
              </div>
              <div>
                <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">LLM Processing Failed</h2>
                <p className="mt-2 max-w-md text-sm text-muted-foreground sm:mt-3">
                  The AI-powered chapter detection could not process this book. Would you like to use the fallback mechanism instead?
                </p>
                <p className="mt-2 max-w-md text-xs text-muted-foreground">
                  The fallback uses pattern matching to detect chapters. It may be less accurate but will still work.
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button
                  onClick={handleRetryWithFallback}
                  disabled={retrying}
                  className="h-10 rounded-full px-5 sm:h-11"
                >
                  {retrying ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      <span>Processing...</span>
                    </>
                  ) : (
                    "Use Fallback"
                  )}
                </Button>
                <Button variant="outline" onClick={resetForm} className="h-10 rounded-full px-5 sm:h-11">
                  Try Different File
                </Button>
              </div>
            </div>
          )}

          {step === "error" && (
            <div className="flex min-h-[400px] flex-col items-center justify-center space-y-5 text-center sm:min-h-[480px]">
              <div className="flex size-14 items-center justify-center rounded-full border border-destructive/30 bg-destructive/10 text-destructive sm:size-16">
                <AlertCircle className="size-6 sm:size-7" />
              </div>
              <div>
                <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">Upload failed</h2>
                <p className="mt-2 max-w-md text-sm text-muted-foreground sm:mt-3">{error}</p>
              </div>
              <Button onClick={() => setStep("form")} variant="outline" className="h-10 rounded-full px-5 sm:h-11">
                Try Again
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
