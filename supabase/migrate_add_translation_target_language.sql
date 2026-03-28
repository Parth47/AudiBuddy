-- Add optional translation target language metadata for per-book TTS routing.
-- Safe to run multiple times.

ALTER TABLE public.books
ADD COLUMN IF NOT EXISTS translation_target_language TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'books_translation_target_language_check'
          AND conrelid = 'public.books'::regclass
    ) THEN
        ALTER TABLE public.books
        ADD CONSTRAINT books_translation_target_language_check
        CHECK (
            translation_target_language IS NULL
            OR translation_target_language IN ('en', 'hi', 'mr')
        );
    END IF;
END $$;
