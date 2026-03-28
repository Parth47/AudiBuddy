-- ============================================
-- Storage Buckets Setup
-- Run this in Supabase SQL Editor AFTER schema.sql
-- ============================================

-- 1. Create storage buckets
INSERT INTO storage.buckets (id, name, public)
VALUES ('pdfs', 'pdfs', false);

INSERT INTO storage.buckets (id, name, public)
VALUES ('audiobooks', 'audiobooks', true);

INSERT INTO storage.buckets (id, name, public)
VALUES ('covers', 'covers', true);

-- 2. Storage policies

-- PDFs: only service role can upload (backend handles this)
-- No public access needed for PDFs

-- Audiobooks: anyone can read (for streaming)
CREATE POLICY "Audiobooks are publicly accessible"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'audiobooks');

-- Covers: anyone can read (for displaying book covers)
CREATE POLICY "Covers are publicly accessible"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'covers');

-- Service role can upload to all buckets (backend uses service role key)
-- Note: service role key already bypasses RLS, so these are for completeness
CREATE POLICY "Service role can upload PDFs"
    ON storage.objects FOR INSERT
    WITH CHECK (bucket_id = 'pdfs' AND auth.role() = 'service_role');

CREATE POLICY "Service role can upload audiobooks"
    ON storage.objects FOR INSERT
    WITH CHECK (bucket_id = 'audiobooks' AND auth.role() = 'service_role');

CREATE POLICY "Service role can upload covers"
    ON storage.objects FOR INSERT
    WITH CHECK (bucket_id = 'covers' AND auth.role() = 'service_role');
