# Nova Command Center - Current State

## Current Project
Nova Command Center — "Alternate Earth" YouTube channel, fully automated video pipeline.

## Current Goal
Keep the pipeline running reliably and improve narration/video quality. No infrastructure migration in progress — backend is stable on Render.

## Current Step (as of 2026-08-09)
- Backend live at https://novacommandcenter.onrender.com (Docker, root dir `backend`, Free instance).
- Supervisor Agent runs every 20 minutes via APScheduler on Render, driving the pipeline automatically. A second, complementary GitHub Actions `supervisor.yml` now runs every 30 minutes to catch and force-retry stuck videos and auto-close stale failure issues — see ARCHITECTURE.md and KNOWN_BUGS.md.
- Narration engine: Edge TTS (en-US-GuyNeural), confirmed stable, in both `narrate.py` (GitHub Actions) and `narration_agent.py` (in-process backend). Chatterbox TTS was tried twice (2026-08-03, 2026-08-08) and reverted both times after near-total synthesis failures.
- `6dc13529` (Silk Road video): the corrupted-script issue is fully resolved and CONFIRMED — real narration audio (4.5MB) verified in storage as of 2026-08-09. Video has 101/101 real Agnes clips, 101/101 shot_durations, and real audio. Fully ready for assembly; nothing left blocking it. `bf465973` (Voynich) was the other corrupted video — fully cleaned up (rows deleted, topic reset to regenerate from scratch).
- Video clip generation (`generate_videos.py`) uses real Agnes video clips with continuity anchoring (character-reference image + last-frame chaining), matching Marius's approach since the 2026-08-03 quality port. A content-policy retry (strip flagged terms, retry once) was ported from Marius on 2026-08-09 to handle WWII/historical-conflict shot rejections, which Nova previously had no recovery path for.
- The 73-issue "Assemble workflow failed" streak (2026-08-06 to 2026-08-08) is root-caused and fixed: a moviepy KeyError on missing ffmpeg fps metadata after the script's own concat step. Fix confirmed live, no new failures since; not yet proven by an actual successful assembly run.
- Schema/repo hygiene: a stray duplicate migration file from a 2026-07-02 GitHub web-editor mistake was found and deleted 2026-08-09. Full repo swept for similar issues — none found elsewhere.
- `.env.example` and `config.py`'s `database_url` default still reference the old SQLite path, stale since the July Postgres/Supabase migration — fix given to Ali for `.env.example`, not yet confirmed committed.
- Long-form videos (longer runtime, not short ~30s clips) is the current content direction.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history — this repo is the single source of truth.
- Update this file whenever the project state changes.
- Do not reference Railway anywhere. It was fully decommissioned 2026-07-15 and is not part of this project's history worth tracking.
- Check GitHub commit history and Supabase directly at the start of every session — do not assume this file or the last handoff is current; changes get pushed directly outside logged sessions.

## Last Updated
2026-08-09
