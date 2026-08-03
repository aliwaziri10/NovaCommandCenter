# Nova Command Center - Task Queue

## In Progress
- (none)

## Next
- **Watch the first live Chatterbox narration run.** It's deployed but untested — confirm it doesn't OOM/crash the Render free-tier backend (see KNOWN_BUGS.md). If it crashes, move synthesis to a separate GitHub Actions job like Marius does.
- Verify YT_REFRESH_TOKEN is actually authorized against the "Alternate Earth" channel (not "Erased"). Chat history claims this was fixed, but the repo has no record confirming it — needs a live check in Google OAuth Playground / a real upload test before trusting it.
- Watch assembly's `-shortest` ffmpeg flag in `assembly_agent.py`: it trims final output to whichever of (silent video, narration audio) is shorter. With longer-form videos now the direction, a shot-duration/narration-length mismatch could silently truncate a video or cut off narration early. Not yet confirmed as an active bug — flagged for monitoring.

## Known Bugs
See KNOWN_BUGS.md for the full log — this section only tracks what's still unresolved:
- Chatterbox in-process OOM risk (untested, see above).
- YT channel authorization (unconfirmed).
- Schema-drift risk: spot-check new model columns against live Supabase schema going forward.

## Completed (recent)
- 2026-08-03 (found undocumented, confirmed live 2026-08-04): Chatterbox TTS ported into `narration_agent.py`, replacing gTTS. Untested in production — see Next/Known Bugs.
- 2026-08-04: Fixed missing `character_reference_url` column on `videos` (added directly to Supabase, plus alembic migration `006`).
- 2026-08-04: Added defensive code/markup guard to `narration_agent.py`.
- 2026-08-04: Confirmed 0 orphaned `tasks` rows remain from "The Hidden Code" cleanup — closed out.
- 2026-08-03: `script_writing_agent.py` patched to reject code/markup/JSON garbage before saving a script.
- 2026-07-29: Fixed dead Pollinations text endpoint in `video_planning_agent.py`.
- 2026-07-15: Backend migration to Render completed and verified end-to-end.

## Rule
Every new task or bug goes here immediately, not just in chat — including anything pushed directly to GitHub outside a session, which must be checked for (diff against last-known commit SHAs) at the start of every new session.
