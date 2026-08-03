# Nova Command Center - Current State

## Current Project
Nova Command Center — "Alternate Earth" YouTube channel, fully automated video pipeline.

## Current Goal
Keep the pipeline running reliably and improve narration/video quality. No infrastructure migration in progress — backend is stable on Render.

## Current Step (as of 2026-08-04)
- Backend live at https://novacommandcenter.onrender.com (Docker, root dir `backend`, Free instance).
- Supervisor Agent runs every 20 minutes via APScheduler on Render, driving the pipeline automatically. Manual GitHub Actions triggers are generally unnecessary.
- Narration bug fixed: `narration_agent.py` had no defense against code/markup text reaching text-to-speech. `script_writing_agent.py` was already patched (2026-08-03) to reject bad AI output before saving a script, but `narration_agent.py` trusted that blindly. Added the same rejection guard directly in `narration_agent.py` so this can't recur even if a future code path bypasses `script_writing_agent`. See KNOWN_BUGS.md for full detail.
- Schema-drift bug also fixed: `character_reference_url` existed on the `Video` model since 2026-08-03 but was never migrated into the live Supabase table, breaking any query that touched `videos` (surfaced via Delete Video Admin 500ing). Column added live, migration `006` added. See KNOWN_BUGS.md.
- Narration engine: Chatterbox TTS (ported from Marius, commit `8284db1`, 2026-08-03) replaced gTTS in `narration_agent.py` — but this was pushed outside a logged session and has **never run in production**. It loads the model in-process on Render's free tier; watch the first real run for a crash/OOM. See KNOWN_BUGS.md.
- Long-form videos (longer runtime, not short ~30s clips) is the current content direction.

## Rules
- Read all files in /brain before starting work.
- Never rely on chat history — this repo is the single source of truth.
- Update this file whenever the project state changes.
- Do not reference Railway anywhere. It was fully decommissioned 2026-07-15 and is not part of this project's history worth tracking.
- Check GitHub commit history and Supabase directly at the start of every session — do not assume this file or the last handoff is current; changes get pushed directly outside logged sessions.

## Last Updated
2026-08-04
