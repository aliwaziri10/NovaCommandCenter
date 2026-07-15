# Nova Command Center - Task Queue

## In Progress
- Verify one full pipeline run end-to-end on Render before touching Railway

## Next
- Re-enable youtube_upload.yml ONLY after YT_REFRESH_TOKEN is regenerated (still unresolved — see Known Bugs)
- Decommission Railway (delete project) once confirmed stable

## Known Bugs
- YouTube uploads were landing on the wrong channel (Erased instead of Alternate Earth) — YT_REFRESH_TOKEN authorized against wrong Google account. Workflow still DISABLED, still needs regenerating via OAuth Playground signed into Alternate Earth's account. NOT YET FIXED.

## Completed
- Confirmed DATABASE_URL already points to Supabase Postgres (vpflhiotidvvvaojwfgf) — no DB migration needed.
- Disabled youtube_upload.yml to stop further wrong-channel uploads.
- Added SUPABASE_URL / SUPABASE_SECRET_KEY to Railway, confirmed /health returns healthy.
- Created Render Web Service (Docker, root dir backend), all env vars copied, confirmed live and healthy at https://novacommandcenter.onrender.com/health.
- Rewrote hardcoded Railway URL to Render URL in all 5 workflow files (assemble.yml, generate_images.yml, generate_video_agnes.yml, generate_videos.yml, narrate.yml).
- Updated youtube_upload.yml's RAILWAY_URL GitHub Secret to Render URL.
