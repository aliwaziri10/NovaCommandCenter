ated# Nova Command Center

Production React + FastAPI dashboard for content operations, revenue tracking, and agent orchestration — with a fully automated, cron-driven video pipeline (script → narration → images → video clips → assembly → YouTube upload).

## Production Stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Recharts
- **Backend:** FastAPI, SQLAlchemy 2.0, Alembic — hosted on **Render** (`novacommandcenter.onrender.com`)
- **Database:** **Supabase Postgres** (production). `DATABASE_URL` is set on Render to Supabase's Supavisor pooler connection string. `database.py` auto-detects Postgres vs SQLite from this URL, so no code changes are needed either way.
- **Media storage:** **Backblaze B2** (bucket `nova-media-zia`) — see "Media Storage" section below. **Supabase Storage is NOT used for anything as of Sep 2, 2026 — do not re-enable it, do not raise its bucket limits, do not suggest it as a fix for anything.**
- **Render free tier sleeps when idle** — `keep-alive.yml` pings `/api/v1/videos` every 10 minutes to prevent cold starts from breaking scheduled runs.

## Media Storage — Backblaze B2 (NOT Supabase Storage)

**Do not use, reference, or re-enable Supabase Storage for any file uploads (video, audio, images, thumbnails).** It was fully migrated away from on Sep 2, 2026, for two independent, permanent reasons:

1. Supabase's Free plan enforces a hard **50MB Global file size limit** that cannot be raised past 50MB by any bucket-level setting, regardless of what any individual bucket's `file_size_limit` is configured to. Nova's CRF20-encoded 1080p renders (600-750MB) can never fit through it.
2. Supabase Storage/REST is separately subject to its own Egress/bandwidth caps per billing cycle, unrelated to (1).

All media now goes to **Backblaze B2** instead:
- Bucket: `nova-media-zia` (globally unique name — plain `nova-media` was already taken)
- Endpoint: `s3.us-east-005.backblazeb2.com`
- Visibility: **Private** (not Public — Backblaze charges a one-time $1 card-verification fee to flip a bucket to Public when the account has no billing history on file, which is not payable here)
- Access: S3-compatible API via `boto3`, credentials in `B2_ENDPOINT_URL` / `B2_KEY_ID` / `B2_APPLICATION_KEY` env vars on Render
- Because the bucket is Private, uploads return a **presigned URL** (temporary signed download link, 6-day expiry) instead of a plain public URL — this is what lets `assemble.py`'s plain unauthenticated HTTP GET still work. If a video is ever read back more than 6 days after upload, its stored URL will have expired and the file will need re-uploading.
- Implemented in `backend/app/supabase_storage.py` — filename and function name (`upload_to_storage`) were deliberately left unchanged from the old Supabase version so no other file's import had to change; only this file's internals are B2-backed now.

`SUPABASE_URL` / `SUPABASE_SECRET_KEY` env vars may still exist on Render as leftover/unused — they are not read by any storage code anymore. Supabase itself is still used, but **only** for `DATABASE_URL` (the Postgres database) — never for storage.

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
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | `youtube_upload.py` — must be authorized against the **Alternate Earth** YouTube channel specifically (see note below) |
| `RAILWAY_URL` (legacy name — actually the Render URL) | `youtube_upload.yml` only; other workflows hardcode the Render URL directly |

**Note on `YT_REFRESH_TOKEN`:** both `Alternate Earth` and `Erased` are managed by the same Google account (ziawaziri@gmail.com), so this is not a "wrong login" problem — it's about which of the two channels was set **active** in that account's YouTube session at the moment OAuth consent was granted. Before generating a new refresh token: go to youtube.com while signed into ziawaziri@gmail.com, click the profile icon, and switch the active channel to **Alternate Earth** first. Only then go through the consent screen.
