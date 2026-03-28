# Audibuddy

> Upload PDFs, auto-generate audiobooks, and stream with a beautiful UI.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   Next.js   │────▶│   FastAPI    │────▶│   Supabase   │
│  Frontend   │     │   Backend    │     │  DB + Storage │
│  (Vercel)   │     │  (Render)    │     │  + Auth       │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │
                    ┌──────▼───────┐
                    │  Piper TTS   │
                    │ (Local/GPU)  │
                    └──────────────┘
```

## Tech Stack

| Layer      | Technology                     |
|------------|--------------------------------|
| Frontend   | Next.js 14 (App Router)        |
| Styling    | TailwindCSS + ShadCN/ui        |
| Backend    | FastAPI (Python 3.11+)         |
| Database   | Supabase (PostgreSQL)          |
| Storage    | Supabase Storage               |
| TTS        | Piper (local inference)        |
| Auth       | Supabase Auth                  |
| Deploy     | Vercel (FE) + Render (BE)      |

## Monorepo Structure

```
audi-buddy/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/routes/   # API endpoints
│   │   ├── core/         # Config, database, security
│   │   ├── models/       # SQLAlchemy/Supabase models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic (PDF, TTS, etc.)
│   │   └── utils/        # Helper functions
│   ├── tests/
│   ├── audio_output/     # Temp audio files before upload
│   ├── requirements.txt
│   └── main.py
├── frontend/             # Next.js frontend
│   ├── src/
│   │   ├── app/          # App Router pages
│   │   ├── components/   # React components
│   │   └── lib/          # Utilities, API client, Supabase
│   └── package.json
├── packages/shared/      # Shared types/constants
├── .env.example
├── .gitignore
└── README.md
```

## Quick Start

See each step's section in the docs for setup instructions.
"# AudiBuddy" 
