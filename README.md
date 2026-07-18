# Nova Command Center

Production React + FastAPI dashboard for content operations, revenue tracking, and agent orchestration — with a fully automated, cron-driven video pipeline (script → narration → images → video clips → assembly → YouTube upload).

## Production Stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Recharts
- **Backend:** FastAPI, SQLAlchemy 2.0, Alembic — hosted on **Render** (`novacommandcenter.onrender.com`)
- **Database:** **Supabase Postgres** (production). `DATABASE_URL` is set on Render to Supabase's Supavisor pooler connection string. `database.py` auto-detects Postgres vs SQLite from this URL, so no code changes are needed either way.
- **Render free tier sleeps when idle** — `keep-alive.yml` pings `/api/v1/videos` every 10 minutes to prevent cold starts from breaking scheduled runs.

## Automated Video Pipeline

Six GitHub Actions workflows, each `workflow_dispatch` (optional `video_id` input) **and** on a cron schedule — the pipeline runs on autopilot with no manual triggering required:

| Workflow | Schedule | Script | Does |
|---|---|---|---|
| `narrate.yml` | every 6h (`:00`) | `narrate.py` | Kokoro TTS narration |
| `generate_images.yml` | every 6h (`:15`) | `generate_images.py` | Shot images |
| `generate_videos.yml` | hourly | `generate_videos.py` | Agnes AI video clips per shot (rate-limited, resumable via `clip_urls`) |
| `assemble.yml` | every 6h (`:45`) | `assemble.py` | Stitches clips + audio into final video; opens a GitHub Issue automatically on failure |
| `youtube_upload.yml` | every 6h (`:15`) | `youtube_upload.py` | Uploads the finished video to YouTube |
| `keep-alive.yml` | every 10min | — | Pings Render so it doesn't cold-sleep |

Each stage auto-selects the next video needing that stage via `GET /api/v1/videos` if no `video_id` is given.

## Local Development (SQLite, optional)

Local dev can run against a throwaway SQLite file instead of Supabase — useful for quick UI/API iteration without touching production data.

### Docker

```bash
cp .env.example .env
docker compose up --build
```

- **App:** http://localhost:3000
- **API docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/health

### Backend (manual)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Local SQLite database (created automatically at ./data/nova.db)
set DATABASE_URL=sqlite:///./data/nova.db
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

To point local dev at the real Supabase DB instead, set `DATABASE_URL` to the Supabase pooler connection string instead of the sqlite one above.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_URL=http://localhost:8000/api/v1` in `.env` for local dev.

## Pages

1. CEO Dashboard — executive overview
2. KPI Dashboard — performance metrics
3. Content Factory — scripts → videos → shorts pipeline
4. Topic Intelligence — trend research and topic management
5. Revenue Center — sponsors and revenue tracking
6. Agent Control Center — AI agent task queue

## API Endpoints

Base path: `/api/v1`

| Endpoint | Description |
|---|---|
| `GET /dashboard/ceo` | CEO dashboard aggregates |
| `GET /dashboard/kpi` | KPI metrics |
| `GET /content/pipeline` | Content pipeline view |
| `GET /revenue/summary` | Revenue breakdown |
| `GET /tasks/agents` | Agent task summary |
| `GET/POST /topics` | Topic CRUD |
| `GET/POST /scripts` | Script CRUD |
| `GET/POST /videos` | Video CRUD |
| `GET/POST /shorts` | Short CRUD |
| `GET/POST /sponsors` | Sponsor CRUD |
| `GET/POST /revenue` | Revenue CRUD |
| `GET/POST /tasks` | Task CRUD |
| `GET/POST /users` | User CRUD |

## Database Tables

`users`, `topics`, `scripts`, `videos`, `shorts`, `sponsors`, `revenue`, `tasks`

## Required Secrets (GitHub Actions)

| Secret | Used by |
|---|---|
| `ASSEMBLY_SECRET` | `generate_images.py`, `assemble.py` |
| `AGNES_API_KEY` | `generate_videos.py` |
| `ACE_MUSIC_API_KEY` | `assemble.py` (background score) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | `youtube_upload.py` — must be authorized against the **Alternator** YouTube channel specifically (see note below) |
| `RAILWAY_URL` (legacy name — actually the Render URL) | `youtube_upload.yml` only; other workflows hardcode the Render URL directly |

**Note on `YT_REFRESH_TOKEN`:** which channel an upload lands on is determined by which YouTube channel was active in the browser at the moment the OAuth consent was granted — not by anything in the code. Always confirm **Alternator** is the active channel on youtube.com *before* generating a new refresh token.
