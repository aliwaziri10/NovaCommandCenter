# Nova Command Center - Architecture

## Backend
FastAPI app, deployed on Render (Docker, root dir `backend`, Free instance): https://novacommandcenter.onrender.com
Database: Supabase Postgres, project `vpflhiotidvvvaojwfgf`.
File storage: Supabase Storage (no persistent disk on Render's free tier).

## Pipeline (in order)
1. **topic_research** (`topic_research_agent.py`) — generates new topic ideas via Pollinations.ai text API.
2. **script_writing** (`script_writing_agent.py`) — generates the narration script in two parts via Pollinations.ai. Rejects code/markup/JSON garbage before saving (fixed 2026-08-03).
3. **video_planning** (`video_planning_agent.py`) — turns the script into a shot-by-shot production plan via Pollinations.ai, scaling shot count to script length.
4. **narration** (`narration_agent.py`, triggered via GitHub Actions `narrate.yml`) — converts script text to speech. Currently gTTS; Chatterbox port pending (see TASK_QUEUE.md). Rejects code/markup before speaking it (fixed 2026-08-04).
5. **asset_generation** (`asset_generation_agent.py`, triggered via `generate_videos.yml`) — generates one image per shot via Pollinations.ai image API.
6. **assembly** (`assembly_agent.py`, triggered via `assemble.yml`) — Ken Burns-style pans on each image, concatenated in blocks via moviepy/ffmpeg, muxed with narration audio.
7. **youtube_upload** (`youtube_upload.yml`) — uploads the finished video to the "Alternate Earth" channel.

## Orchestration
`supervisor_agent.py` runs every 20 minutes via APScheduler on Render. It scans the database for the next unfinished pipeline stage and either runs it directly (topic_research, script_writing, video_planning) or triggers the matching GitHub Actions workflow (narration, video_clips, assembly) via `github_actions_client.py`. There is no proactive stuck/failure alert system — permanently stalled videos must be found via direct Supabase queries.

## Strategy research
`strategy_research_agent.py` pulls recent video titles/view counts from a fixed competitor list plus Nova's own channel via the YouTube Data API (`YOUTUBE_API_KEY`, `NOVA_YOUTUBE_CHANNEL_ID` env vars), runs weekly, and feeds a short note into `script_writing_agent`'s prompt.

## Update this file
Whenever a pipeline stage is added, removed, or fundamentally changed.
