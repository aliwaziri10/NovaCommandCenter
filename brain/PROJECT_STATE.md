# Nova Command Center - Current State

## Current Project
Nova Command Center — Railway to Render/Supabase migration

## Current Goal
Move Nova backend off Railway before billing starts (~15 days from 2026-07-15).

## Current Step
Waiting on SUPABASE_URL and SUPABASE_SECRET_KEY being added to Railway's Variables tab (fixes a live upload bug AND unblocks the Render move). After that: create Render Web Service, set env vars, get the new URL, rewrite 5 workflow files that hardcode the old Railway URL.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history.
- Update this file whenever the project state changes.

## Last Updated
2026-07-15

# Nova Command Center - Task Queue

## In Progress
- Railway to Render/Supabase migration (see DECISIONS.md, 2026-07-15)
- Waiting on SUPABASE_URL / SUPABASE_SECRET_KEY added to Railway

## Next
- Create Render Web Service (root dir: backend, Dockerfile auto-detected)
- Render env vars: DATABASE_URL (Supabase pooler string, already confirmed correct), SUPABASE_URL, SUPABASE_SECRET_KEY, CORS_ORIGINS
- Get new Render live URL
- Rewrite hardcoded Railway URL in: assemble.yml, generate_images.yml, generate_video_agnes.yml, generate_videos.yml, narrate.yml
- Update youtube_upload.yml's RAILWAY_URL secret to the new Render URL
- Re-enable youtube_upload.yml ONLY after YT_REFRESH_TOKEN is regenerated (see Known Bugs)
- Decommission Railway once Render is confirmed working

## Known Bugs
- YouTube uploads were landing on the wrong channel (Erased instead of Alternate Earth) — YT_REFRESH_TOKEN was authorized against the wrong Google account. Workflow currently DISABLED. Fix: regenerate token via OAuth Playground signed into Alternate Earth's account. "Silk Road Reimagined" was set Private on Erased as cleanup.
- SUPABASE_URL / SUPABASE_SECRET_KEY were missing from Railway entirely — upload_to_storage() in upload_router.py likely failing on every narration/video upload. Fix in progress.

## Completed
- Confirmed DATABASE_URL already points to Supabase Postgres (vpflhiotidvvvaojwfgf) — no DB migration needed.
- Diagnosed real production pipeline: GitHub Actions does the heavy work, POSTs results to Railway backend, backend pushes to Supabase Storage.
- Disabled youtube_upload.yml to stop further wrong-channel uploads.

- # Nova Command Center - Decisions

## Purpose
Record important technical and business decisions so future sessions understand why they were made.

## Decisions

### 2026-07-08
- Agnes API requests are sent sequentially to avoid HTTP 429 rate limits.
- Progress is saved after every generated clip.
- Never rely on chat history.
- The /brain folder is the single source of truth for project memory.

### 2026-07-15
- Migrating off Railway to Render (free tier) before Railway billing starts. Database stays on Supabase (already there). File storage moves fully to Supabase Storage (bucket: nova-media) — not any host's local disk — since Render's free tier has no persistent disk.
- Chose Render over Oracle Cloud Always Free (requires Linux/SSH admin, recently had its free allocation quietly cut) and Google Cloud Run (requires gcloud/Docker familiarity) — Render deploys straight from GitHub with no server admin, best fit for non-technical operation.
- YT_REFRESH_TOKEN in this repo's secrets was generated against the Erased channel's Google account by mistake. No shared credentials exist between marius-command-center and NovaCommandCenter otherwise.

## Rule
Every significant decision must be added here with its reason.
