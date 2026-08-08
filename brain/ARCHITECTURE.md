# Nova Command Center - Architecture

## Backend
FastAPI app, deployed on Render (Docker, root dir `backend`, Free instance): https://novacommandcenter.onrender.com
Database: Supabase Postgres, project `vpflhiotidvvvaojwfgf`.
File storage: Supabase Storage (no persistent disk on Render's free tier).

## Pipeline (in order)
1. **topic_research** (`topic_research_agent.py`) — generates new topic ideas via Pollinations.ai text API.
2. **script_writing** (`script_writing_agent.py`) — generates the narration script in two parts via Pollinations.ai. Rejects code/markup/JSON garbage before saving (fixed 2026-08-03).
3. **video_planning** (`video_planning_agent.py`) — turns the script into a shot-by-shot production plan via Pollinations.ai, scaling shot count to script length.
4. **narration** (`narration_agent.py` / `.github/scripts/narrate.py`) — converts script text to speech via Edge TTS (en-US-GuyNeural), sentence-level synthesis with real pauses; computes real per-shot `shot_durations` from actual audio length. Chatterbox TTS was tried twice (2026-08-03, 2026-08-08) and reverted both times after near-total synthesis failures - Edge TTS is the confirmed stable choice, not a placeholder.
5. **video clip generation** (`.github/scripts/generate_videos.py`) — CORRECTED 2026-08-09: this is NOT still-image Ken Burns pans. As of the 2026-08-03 quality port from Marius, this generates one real Agnes video clip per shot (agnes-video-v2.0), with continuity anchoring (a character-reference image for shot 0, then each subsequent shot's clip chained to the previous shot's last extracted frame as an image-to-video anchor), real shot-duration-based frame counts (not a flat hardcoded length), and a content-policy retry (added 2026-08-09, strips flagged terms and retries once on rejection). `asset_generation_agent.py` (Pollinations image API, one still image per shot) is superseded/no longer the active path for clip generation as of this port - verify at next session whether it's still called anywhere or is now dead code.
6. **assembly** (`assembly_agent.py` / `.github/scripts/assemble.py`) — downloads the real video clips (not images), renders in blocks via moviepy/ffmpeg with crossfades, mixes narration + extracted native clip audio, applies a cinematic color grade and loudness normalization. Requires ALL shots to have real video clips - does not fall back to still images.
7. **youtube_upload** (`youtube_upload.yml`) — uploads the finished video to the "Alternate Earth" channel.

## Orchestration
`supervisor_agent.py` runs every 20 minutes via APScheduler on Render. It scans the database for the next unfinished pipeline stage and either runs it directly (topic_research, script_writing, video_planning) or triggers the matching GitHub Actions workflow (narration, video_clips, assembly) via `github_actions_client.py`.

ADDED 2026-08-09: a second, GitHub Actions-side `supervisor.yml` workflow now runs every 30 minutes, closing the gap this section used to describe ("no proactive stuck/failure alert system"). It force-triggers a stage directly via `workflow_dispatch` if a video has been stuck past a normal cron window for that stage, auto-closes workflow-failure issues that predate a later fix commit to the relevant script, and escalates to one "NEEDS HUMAN" issue (not repeat spam) after 3 failed auto-retries on the same video/stage. This is a monitoring/recovery layer on top of `supervisor_agent.py`, not a replacement for it - `supervisor_agent.py` still owns normal forward progress; the new workflow only intervenes when something's stuck.

## Strategy research
`strategy_research_agent.py` pulls recent video titles/view counts from a fixed competitor list plus Nova's own channel via the YouTube Data API (`YOUTUBE_API_KEY`, `NOVA_YOUTUBE_CHANNEL_ID` env vars), runs weekly, and feeds a short note into `script_writing_agent`'s prompt.

## Update this file
Whenever a pipeline stage is added, removed, or fundamentally changed.
