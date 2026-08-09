# Nova Command Center - Current State

## Current Project
Nova Command Center — "Alternate Earth" YouTube channel, fully automated video pipeline.

## Current Goal
Keep the pipeline running reliably and improve narration/video quality. No infrastructure migration in progress — backend is stable on Render.

## Current Step (as of 2026-08-09, after full architecture audit)
- Backend live at https://novacommandcenter.onrender.com (Docker, root dir `backend`, Free instance).
- Supervisor Agent runs every 20 minutes via APScheduler on Render, driving the pipeline automatically. A second, complementary GitHub Actions `supervisor.yml` now runs every 30 minutes to catch and force-retry stuck videos and auto-close stale failure issues — not yet observed in a real run.
- Narration engine: Edge TTS, voice **en-US-GuyNeural**, in both `narrate.py` (GitHub Actions) and `narration_agent.py` (in-process backend). FIXED 2026-08-09: both files were silently defaulting to `en-US-AriaNeural` (female) since the Edge TTS revert — narrate.yml had no override, so the wrong voice was live in production despite docs always saying GuyNeural. Now corrected and confirmed committed in both files.
- `6dc13529` (Silk Road video): fully ready for assembly (101/101 real Agnes clips, 101/101 shot_durations, real 4.5MB narration audio). Waiting on the assemble stage to pick it up. NEXT SESSION: confirm it actually reached status=assembled and check final quality.
- Content-policy retry (strip flagged terms, retry once on Agnes rejection) CONFIRMED live in `generate_videos.py` — was previously logged as "unconfirmed," now verified directly on GitHub.
- Long-video audio/video length mismatch risk: `assemble.py` already has a `tpad` freeze-frame pad for when video is shorter than narration — not previously documented as handled. Still not proven on a real end-to-end run.
- A full audit this session found several stale/wrong brain-doc claims and two other real findings — see KNOWN_BUGS.md "Unresolved" section for the complete list (shot-parsing regex inconsistency across scripts, asset_generation_agent.py confirmed NOT dead code, generate_images.py never actually deleted, unused ACE_MUSIC_API_KEY secret, .env.example never created).
- Long-form videos (longer runtime, not short ~30s clips) is the current content direction.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history — this repo is the single source of truth.
- Update this file whenever the project state changes.
- Do not reference Railway anywhere in new writing. Note: RAILWAY_URL is still the actual env var name used by every script/workflow (harmless, just naming debt) — do not "fix" this without checking every script that reads it.
- Check GitHub commit history and Supabase directly at the start of every session — do not assume this file or the last handoff is current; changes get pushed directly outside logged sessions.
- GitHub write access for Claude (GitHub:create_or_update_file) is confirmed still 403 on this repo as of 2026-08-09 — always deliver fixes as full-file copy-paste + direct /edit/main/ link, never a diff or partial snippet, and never say "change line N" (line numbers in the web editor don't match).

## Last Updated
2026-08-09
