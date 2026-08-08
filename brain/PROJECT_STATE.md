# Nova Command Center - Current State

## Current Project
Nova Command Center — "Alternate Earth" YouTube channel, fully automated video pipeline.

## Current Goal
Keep the pipeline running reliably and improve narration/video quality. No infrastructure migration in progress — backend is stable on Render.

## Current Step (as of 2026-08-09)
- Backend live at https://novacommandcenter.onrender.com (Docker, root dir `backend`, Free instance).
- Supervisor Agent runs every 20 minutes via APScheduler on Render, driving the pipeline automatically. Manual GitHub Actions triggers are generally unnecessary.
- Narration engine: back on Edge TTS as of 2026-08-09, in both `narrate.py` (GitHub Actions) and `narration_agent.py` (in-process backend). Chatterbox TTS (ported 2026-08-03) was tried and reverted after its one live run on 2026-08-08 produced ~4s of audio for a ~555s script — a near-total synthesis failure, not caught by any exception at the time. `narrate.yml`'s dependency install was stale (still installed Chatterbox packages) until fixed 2026-08-09 — confirmed working via a manual run.
- Two known-corrupted Script rows (`scripts.content` literally reading "Script generation failed on part 1 — try running this task again.") were found and traced to before the 2026-08-08 fix in `script_writing_agent.py` that now raises instead of saving a placeholder. One (video `bf465973`, Voynich Manuscript topic) has been fully cleaned up and its topic reset to regenerate. The other (video `6dc13529`, Silk Road topic, 101 real clips already generated) is NOT yet fixed — see KNOWN_BUGS.md and TASK_QUEUE.md for the careful fix needed (its production_plan and clips are real and must be preserved).
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
