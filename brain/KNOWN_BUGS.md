# Nova Command Center - Known Bugs

## Fixed

### Delete Video endpoint crashed with 500 — missing DB column (fixed 2026-08-04)
`character_reference_url` was added to `Video` model (`backend/app/models/video.py`) on 2026-08-03 as part of the Marius continuity-anchoring port, but no migration was ever run against Supabase. Model and live table drifted apart — any query touching `videos` (including Delete Video Admin) failed with `psycopg2.errors.UndefinedColumn`. Fixed by adding the column directly to Supabase and adding the missing alembic migration (`006_add_character_reference_url_to_videos.py`) so schema history matches the model going forward.

### Narration spoke raw code/markup instead of the script (fixed 2026-08-04)
`script_writing_agent.py` was patched 2026-08-03 to reject code/HTML/JSON garbage from Pollinations before saving it as a script. But `narration_agent.py` had zero defense of its own — it would TTS whatever was in `script.content` with no check. Any script saved before the 2026-08-03 fix, or reaching narration through any future code path, was unprotected. Fixed by adding the same rejection guard directly inside `narration_agent.py`, so narration defends itself instead of trusting script_writing to have already done it.

### Script generation accepted malformed AI output as valid script text (fixed 2026-08-03)
Old fallback logic accepted any response over 100 characters as valid script text, including raw HTML error pages, JSON fragments, or code from a degraded/erroring Pollinations API call. Fixed with `_looks_like_code_or_markup()` in `script_writing_agent.py`.

### video_planning silently failed forever after Pollinations endpoint retirement (fixed 2026-07-29)
`text.pollinations.ai` was retired in favor of `gen.pollinations.ai/text`. Every video_planning call failed silently and the supervisor kept rescheduling the same doomed task instead of surfacing it as broken — no new video was planned for 6 days.

## Unresolved / needs verification

- **UNTESTED IN PRODUCTION — Chatterbox TTS ported into `narration_agent.py`, replacing gTTS (commit `8284db1`, 2026-08-03 22:04 UTC).** Pushed directly via the GitHub web editor, outside any logged Claude session — it was missing from `TASK_QUEUE.md`/`PROJECT_STATE.md` until this check found it live. Confirmed via Supabase: no `narration` task has run since this commit, so it has never executed in production. Risk flagged in the code's own comments: unlike Marius (Chatterbox runs in its own GitHub Actions job, ~7GB RAM), this loads the neural model **in-process inside the FastAPI backend on Render's free tier**, triggered by the Supervisor every 20 minutes. If the free tier can't hold the model in memory, this can crash/restart-loop the entire backend, not just fail narration. **Watch the next narration run closely.** If it crashes, move Chatterbox synthesis out of the in-process agent into a separate job (mirror Marius), rather than running it inside the always-on API process.
- **YouTube channel authorization**: chat history claims `YT_REFRESH_TOKEN` was fixed to target "Alternate Earth" instead of "Erased", but nothing in this repo confirms it. Needs a live OAuth Playground check or a real test upload before being trusted.
- **Long-video audio/video length mismatch risk**: `assembly_agent.py` uses ffmpeg's `-shortest` flag when muxing narration audio with the assembled silent video, which trims to whichever is shorter. Now that Nova targets longer-form videos, a shot-duration/narration-length mismatch could silently cut a video short or truncate narration. Not yet confirmed to have happened — watch for it.
- **Schema drift risk**: `character_reference_url` proved a model column can be added without its migration ever running. Worth spot-checking new model columns against live Supabase schema going forward.

## Resolved cleanup (verified 2026-08-04)
- 27 orphaned `tasks` rows referencing the deleted "The Hidden Code" video: reconfirmed via direct Supabase query — **0 rows remain.** No longer a pending item.

## Rule
Every new bug (and its fix, once resolved) gets logged here immediately — including changes pushed directly by Ali outside a Claude session, which must be checked for on every handoff rather than assumed absent.
