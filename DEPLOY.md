# Audibuddy Deployment Guide

## Architecture Overview

Audibuddy has two modes controlled by a single environment variable:

- **Local (Admin) mode** — `ADMIN_MODE=true` — Full access: upload PDFs, edit metadata, delete books, generate audio. Run this on your machine.
- **Published (Public) mode** — `ADMIN_MODE=false` — Read-only: visitors can browse and listen to audiobooks. Upload/edit/delete/generate buttons are hidden. Backend rejects write requests with 403.

Both modes share the same Supabase database. You add books locally, they appear on the live site instantly.

## Free Stack Summary

| Service | Free Tier | What It Does |
|---------|-----------|--------------|
| **Supabase** | 500 MB DB, 1 GB storage, 2 GB bandwidth/month | Database + file storage (PDFs, audio, covers) |
| **Vercel** | 100 GB bandwidth/month, serverless functions | Hosts the Next.js frontend |
| **Render** | 750 hours/month (spins down after 15 min idle) | Hosts the FastAPI backend |
| **Google Gemini** | 1M tokens/day, 15 RPM | Chapter detection (LLM) |
| **ElevenLabs** | 10,000 chars/month per key | High-quality TTS |
| **Edge-TTS** | Unlimited, free | Fallback TTS (Microsoft voices) |

## Step 1: Deploy the Backend (Render)

1. Push your code to GitHub
2. Go to [render.com](https://render.com) and sign up (free)
3. Click **New > Web Service** and connect your GitHub repo
4. Configure:
   - **Root Directory**: `backend`
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
5. Add these environment variables in the Render dashboard:

| Variable | Value |
|----------|-------|
| `ADMIN_MODE` | `false` |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_ANON_KEY` | Your Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Your Supabase service role key |
| `CORS_ORIGINS` | Your Vercel frontend URL (e.g. `https://audibuddy.vercel.app`) |
| `GOOGLE_GEMINI_API_KEYS` | Your Gemini API key(s) |
| `ELEVENLABS_API_KEYS` | Your ElevenLabs key(s) (optional) |
| `EDGE_TTS_VOICE` | `en-US-AriaNeural` |

6. Click **Create Web Service**. Note the URL (e.g. `https://audibuddy-api.onrender.com`)

## Step 2: Deploy the Frontend (Vercel)

1. Go to [vercel.com](https://vercel.com) and sign up (free)
2. Click **New Project** and import your GitHub repo
3. Configure:
   - **Root Directory**: `frontend`
   - **Framework Preset**: Next.js (auto-detected)
4. Add these environment variables:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | Your Render backend URL (e.g. `https://audibuddy-api.onrender.com`) |
| `NEXT_PUBLIC_SUPABASE_URL` | Your Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Your Supabase anon key |

5. Click **Deploy**

## Step 3: Update CORS

After deploying both services, go back to Render and update the `CORS_ORIGINS` environment variable to your actual Vercel URL.

## Adding New Books (Admin Workflow)

Since the published site is read-only, you add books from your local machine:

1. In your local `backend/.env`, make sure `ADMIN_MODE=true`
2. Start the local backend: `cd backend && uvicorn main:app --reload`
3. Start the local frontend: `cd frontend && npm run dev`
4. Open `http://localhost:3000/upload` and upload your PDF
5. Generate the audio from the book detail page
6. The book is stored in Supabase — it will appear on the live site immediately with no redeployment needed

## Folder Structure for Deployment

```
AudiBuddy/
├── frontend/          ← Deploy this to Vercel
│   ├── src/
│   ├── package.json
│   └── next.config.ts
│
├── backend/           ← Deploy this to Render
│   ├── app/
│   ├── main.py
│   └── requirements.txt
│
└── supabase/          ← Run these SQL scripts in Supabase SQL editor
    ├── schema.sql
    └── storage_setup.sql
```

## Notes

- **Render free tier spins down after 15 minutes of inactivity.** The first request after idle will take ~30 seconds. This is normal for the free tier. Upgrade to a paid plan ($7/mo) to keep it always on.
- **Supabase audio files are served directly from Supabase Storage CDN**, so audio playback is fast regardless of Render's state.
- **No code changes are needed between local and deployed versions.** The only difference is the `ADMIN_MODE` environment variable.

## Upload Error Fix (400 on `/rest/v1/books?id=eq...`)

If PDF upload fails with a `400 Bad Request` from Supabase when processing fails, your `books.status` constraint is likely missing `llm_failed`.

Run `supabase/migrate_allow_llm_failed_status.sql` once in the Supabase SQL editor.
