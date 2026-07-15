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
