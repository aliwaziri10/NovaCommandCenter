# Nova Command Center - Task Queue

## In Progress
- Render deployment (see PROJECT_STATE.md) — waiting for Render to finish building and provide its live URL

## Next
- Once Render is live: rewrite hardcoded Railway URL (https://novacommandcenter-production.up.railway.app) in these 5 files, full-file replace, no partial edits: assemble.yml, generate_images.yml, generate_video_agnes.yml, generate_videos.yml, narrate.yml
- Update youtube_upload.yml's RAILWAY_URL secret (GitHub Secrets, not the yml file) to the new Render URL
- Re-enable youtube_upload.yml ONLY after YT_REFRESH_TOKEN is regenerated (still unresolved — see Known Bugs)
- Verify one full pipeline run end-to-end on Render before touching Railway
- Decommission Railway (delete project) once confirmed stable

## Known Bugs
- YouTube uploads were landing on the wrong channel (Erased instead of Alternate Earth) — YT_REFRESH_TOKEN authorized against wrong Google account. Workflow still DISABLED, still needs regenerating via OAuth Playground signed into Alternate Earth's account. NOT YET FIXED.
- SUPABASE_URL / SUPABASE_SECRET_KEY missing from Railway — FIXED 2026-07-15, confirmed healthy.

## Completed
- Confirmed DATABASE_URL already points to Supabase Postgres (vpflhiotidvvvaojwfgf) — no DB migration needed.
- Disabled youtube_upload.yml to stop further wrong-channel uploads.
- Added SUPABASE_URL / SUPABASE_SECRET_KEY to Railway, confirmed /health returns healthy.
