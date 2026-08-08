# Nova Command Center - Task Queue

## In Progress
- None currently blocking. `6dc13529` (Silk Road video) is fully ready for assembly (101/101 clips, 101/101 shot_durations, real 4.5MB narration audio confirmed) - waiting on the assemble stage to run (either the 6h cron, the in-process Supervisor Agent, or the new GitHub Actions supervisor workflow, whichever picks it up first). NEXT SESSION: confirm it actually reached status=assembled and check final video quality (lighting, sync, no truncation from the -shortest ffmpeg flag).

## Next
- Confirm .env.example commit landed (Supabase DATABASE_URL, replacing stale SQLite default).
- Investigate HOW bf465973 and 6dc13529 ended up with byte-identical production_plan content — video_planning_agent.py has no known copy path; read it closely next time it's touched. See KNOWN_BUGS.md.
- Verify YT_REFRESH_TOKEN is authorized against "Alternate Earth", not "Erased" — live OAuth Playground check or real upload test.
- Watch assembly's -shortest ffmpeg flag, especially on 6dc13529 once it assembles with its new narration length vs. its original plan's shot durations.
- Confirm the new supervisor.yml workflow's first live runs behave as expected (force-triggers, auto-closes, escalation) — was just added this session, not yet observed in a real run.
- Confirm the content-policy-retry port in generate_videos.py (handed to Ali as a full-file edit this session) actually got committed, and watch for it firing on a real historical-conflict shot.

## Known Bugs
See KNOWN_BUGS.md for the full log — unresolved items only:
- .env.example / config.py stale SQLite default (fix given, not confirmed committed).
- production_plan duplication root cause (symptom fixed, mechanism unknown).
- YT channel authorization (unconfirmed).
- assembly -shortest flag risk (monitoring).

## Completed (recent)
- 2026-08-09: Confirmed 6dc13529's re-narration succeeded (4.5MB real audio file, not the ~40KB stale Chatterbox one) - fully unblocked and ready for assembly.
- 2026-08-09: Root-caused and confirmed the fix (already committed by Ali) for 73 consecutive "Assemble workflow failed" issues - moviepy KeyError on missing fps metadata after ffmpeg concat, fixed by reading duration from ffmpeg's own output instead.
- 2026-08-09: Built and Ali committed a new Supervisor workflow (supervisor.yml + supervisor.py) - force-retries stuck videos, auto-closes stale failure issues, escalates genuinely broken ones instead of retrying forever.
- 2026-08-09: Ported Marius's content-policy retry fix (strip flagged terms, retry once) into generate_videos.py - handed to Ali as a full-file edit.
- 2026-08-09: Fixed narrate.yml stale Chatterbox deps (now installs edge-tts).
- 2026-08-09: Found and deleted stray duplicate migration file (nested alembic path). Full repo swept — no other instances.
- 2026-08-09: Cleaned up bf465973 (Voynich) — deleted corrupted Video/Script rows + 4 orphaned tasks, topic reset to regenerate.
- 2026-08-09: Diagnosed production_plan duplication between bf465973 and 6dc13529; confirmed via plan content which video the real plan/clips belong to (6dc13529).
- 2026-08-09: Wrote real narration script directly for 6dc13529 (Silk Road) to preserve its 101 existing clips and production_plan without regenerating them.
- 2026-08-04: Fixed missing character_reference_url column (migration 006).
- 2026-08-04: Added defensive code/markup guard to narration_agent.py.
- 2026-08-03: script_writing_agent.py patched to reject code/markup/JSON garbage.
- 2026-07-29: Fixed dead Pollinations text endpoint.
- 2026-07-15: Backend migration to Render completed and verified.

## Rule
Every new task or bug goes here immediately — including anything pushed directly to GitHub outside a session.
