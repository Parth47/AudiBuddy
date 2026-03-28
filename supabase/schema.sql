-- ============================================
-- AudiBuddy Database Schema
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ============================================

-- 1. BOOKS TABLE
-- Stores metadata about each uploaded book
CREATE TABLE books (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT DEFAULT 'Unknown',
    description TEXT,
    cover_image_url TEXT,
    genre TEXT DEFAULT 'General',
    language TEXT DEFAULT 'en',
    total_chapters INTEGER DEFAULT 0,
    total_duration_seconds INTEGER DEFAULT 0,
    pdf_storage_path TEXT,          -- path in Supabase Storage
    status TEXT DEFAULT 'processing' CHECK (status IN ('processing', 'ready', 'error')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. CHAPTERS TABLE
-- Stores each chapter's text and audio info
CREATE TABLE chapters (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    book_id UUID REFERENCES books(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    title TEXT DEFAULT 'Untitled Chapter',
    text_content TEXT,              -- extracted chapter text
    audio_storage_path TEXT,        -- path in Supabase Storage
    duration_seconds INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'ready', 'error')),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(book_id, chapter_number)
);

-- 3. USER PROGRESS TABLE
-- Tracks where each user left off in each book
CREATE TABLE user_progress (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,          -- from Supabase Auth
    book_id UUID REFERENCES books(id) ON DELETE CASCADE,
    chapter_id UUID REFERENCES chapters(id) ON DELETE CASCADE,
    progress_seconds FLOAT DEFAULT 0,  -- seconds into the current chapter
    completed BOOLEAN DEFAULT FALSE,
    last_played_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, book_id)
);

-- 4. FAVORITES TABLE
-- Books the user has favorited
CREATE TABLE favorites (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,          -- from Supabase Auth
    book_id UUID REFERENCES books(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, book_id)
);

-- ============================================
-- INDEXES (for fast queries)
-- ============================================
CREATE INDEX idx_chapters_book_id ON chapters(book_id);
CREATE INDEX idx_chapters_book_number ON chapters(book_id, chapter_number);
CREATE INDEX idx_user_progress_user ON user_progress(user_id);
CREATE INDEX idx_user_progress_last_played ON user_progress(user_id, last_played_at DESC);
CREATE INDEX idx_favorites_user ON favorites(user_id);
CREATE INDEX idx_books_genre ON books(genre);
CREATE INDEX idx_books_status ON books(status);

-- ============================================
-- AUTO-UPDATE updated_at TRIGGER
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER books_updated_at
    BEFORE UPDATE ON books
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================

-- Enable RLS on all tables
ALTER TABLE books ENABLE ROW LEVEL SECURITY;
ALTER TABLE chapters ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE favorites ENABLE ROW LEVEL SECURITY;

-- Books & Chapters: anyone can read, only service role can insert/update
CREATE POLICY "Books are viewable by everyone"
    ON books FOR SELECT
    USING (true);

CREATE POLICY "Chapters are viewable by everyone"
    ON chapters FOR SELECT
    USING (true);

-- User Progress: users can only access their own data
CREATE POLICY "Users can view own progress"
    ON user_progress FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own progress"
    ON user_progress FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own progress"
    ON user_progress FOR UPDATE
    USING (auth.uid() = user_id);

-- Favorites: users can only access their own favorites
CREATE POLICY "Users can view own favorites"
    ON favorites FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own favorites"
    ON favorites FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own favorites"
    ON favorites FOR DELETE
    USING (auth.uid() = user_id);
