# Nova Command Center - Decisions

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
