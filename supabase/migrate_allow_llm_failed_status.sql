-- Add llm_failed as an allowed books.status value for existing projects.
-- Safe to run multiple times.

DO $$
DECLARE
    existing_status_constraint text;
BEGIN
    SELECT conname
    INTO existing_status_constraint
    FROM pg_constraint
    WHERE conrelid = 'public.books'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%status%';

    IF existing_status_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.books DROP CONSTRAINT %I', existing_status_constraint);
    END IF;

    ALTER TABLE public.books
    ADD CONSTRAINT books_status_check
    CHECK (status IN ('processing', 'ready', 'error', 'llm_failed'));
END $$;
