# Nova Command Center - Current State

## Current Project
Nova Command Center — Railway to Render/Supabase migration

## Current Goal
COMPLETE. Backend fully migrated off Railway to Render.

## Current Step
Migration finished. Backend live at https://novacommandcenter.onrender.com (Docker, root dir backend, Free instance). All 5 workflow files (assemble.yml, generate_images.yml, generate_video_agnes.yml, generate_videos.yml, narrate.yml) point to Render. youtube_upload.yml's RAILWAY_URL secret updated to Render URL. Pipeline verified working end-to-end against Render. Railway project deleted (scheduled removal within 48h of 2026-07-15).

Remaining unrelated task: re-enable youtube_upload.yml once YT_REFRESH_TOKEN is regenerated (see TASK_QUEUE.md Known Bugs) — not part of this migration.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history.
- Update this file whenever the project state changes.

## Last Updated
2026-07-15
