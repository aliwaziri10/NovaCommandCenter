# Nova Command Center - Current State

## Current Project
Nova Command Center — "Alternate Earth" YouTube channel, fully automated video pipeline.

## Current Goal
Keep the pipeline running reliably and improve narration/video quality. No infrastructure migration in progress — backend is stable on Render.

## Current Step (as of 2026-08-04)
- Backend live at https://novacommandcenter.onrender.com (Docker, root dir `backend`, Free instance).
- Supervisor Agent runs every 20 minutes via APScheduler on Render, driving the pipeline automatically. Manual GitHub Actions triggers are generally unnecessary.
- Narration bug fixed today: `narration_agent.py` had no defense against code/markup text reaching text-to-speech. `script_writing_agent.py` was already patched (2026-08-03) to reject bad AI output before saving a script, but `narration_agent.py` trusted that blindly. Added the same rejection guard directly in `narration_agent.py` so this can't recur even if a future code path bypasses `script_writing_agent`. See KNOWN_BUGS.md for full detail.
- Schema-drift bug also fixed today: `character_reference_url` existed on the `Video` model since 2026-08-03 but was never migrated into the live Supabase table, breaking any query that touched `videos` (surfaced via Delete Video Admin 500ing). Column added live, migration `006` added. See KNOWN_BUGS.md.
- Narration engine is still plain gTTS (`backend/requirements.txt`, `narration_agent.py`). Chatterbox TTS (already used in Marius) has NOT been ported to Nova yet — tracked in TASK_QUEUE.md.
- Long-form videos (longer runtime, not short ~30s clips) is the current content direction.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history — this repo is the single source of truth.
- Update this file whenever the project state changes.
- Do not reference Railway anywhere. It was fully decommissioned 2026-07-15 and is not part of this project's history worth tracking.

## Last Updated
2026-08-04
