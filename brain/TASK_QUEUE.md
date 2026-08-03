# Nova Command Center - Task Queue

## In Progress
- (none)

## Next
- Port Chatterbox TTS from Marius into Nova, replacing gTTS in `narration_agent.py` and `backend/requirements.txt`. Marius's working reference: Edge TTS/Chatterbox setup in its own narration code — use it as the model for Nova's port. This is the top priority after today's narration-guard fix, since gTTS is the weakest link in current output quality.
- Verify YT_REFRESH_TOKEN is actually authorized against the "Alternate Earth" channel (not "Erased"). Chat history claims this was fixed, but the repo has no record confirming it — needs a live check in Google OAuth Playground / a real upload test before trusting it.
- Watch assembly's `-shortest` ffmpeg flag in `assembly_agent.py`: it trims final output to whichever of (silent video, narration audio) is shorter. With longer-form videos now the direction, a shot-duration/narration-length mismatch could silently truncate a video or cut off narration early. Not yet confirmed as an active bug — flagged for monitoring, investigate if a published long video looks cut short.
- Decide on 27 leftover orphaned `tasks` rows referencing the deleted "The Hidden Code" video, plus possible orphaned storage files for it. Low urgency, cosmetic only.

## Known Bugs
See KNOWN_BUGS.md for the full log — this section only tracks what's still unresolved:
- YT channel authorization (see above, unconfirmed).
- Schema-drift risk: spot-check new model columns against live Supabase schema going forward.

## Completed (recent)
- 2026-08-04: Fixed missing `character_reference_url` column on `videos` (added directly to Supabase, plus added the missing alembic migration `006`). Root cause: column was added to the model 2026-08-03 without a matching migration ever run.
- 2026-08-04: Added defensive code/markup guard to `narration_agent.py` (see KNOWN_BUGS.md).
- 2026-08-03: `script_writing_agent.py` patched to reject code/markup/JSON garbage before saving a script (root cause of the narration-reads-code bug).
- 2026-07-29: Fixed dead Pollinations text endpoint in `video_planning_agent.py` (migrated to `gen.pollinations.ai/text`).
- 2026-07-15: Backend migration to Render completed and verified end-to-end.

## Rule
Every new task or bug goes here immediately, not just in chat.
