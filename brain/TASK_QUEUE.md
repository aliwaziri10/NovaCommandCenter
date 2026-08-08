# Nova Command Center - Task Queue

## In Progress
- 6dc13529 (Silk Road video): real script written manually into Supabase, audio_path cleared, narrate.yml re-run initiated 2026-08-09. NEXT SESSION: verify the narration actually succeeded (check storage.objects size for narration/6dc13529..., should be well over 1MB) and that assembly/upload proceed normally from there.

## Next
- Confirm .env.example commit landed (Supabase DATABASE_URL, replacing stale SQLite default).
- Investigate HOW bf465973 and 6dc13529 ended up with byte-identical production_plan content — video_planning_agent.py has no known copy path; read it closely next time it's touched. See KNOWN_BUGS.md.
- Verify YT_REFRESH_TOKEN is authorized against "Alternate Earth", not "Erased" — live OAuth Playground check or real upload test.
- Watch assembly's -shortest ffmpeg flag, especially on 6dc13529 once it assembles with its new narration length vs. its original plan's shot durations.

## Known Bugs
See KNOWN_BUGS.md for the full log — unresolved items only:
- .env.example / config.py stale SQLite default (fix given, not confirmed committed).
- production_plan duplication root cause (symptom fixed, mechanism unknown).
- YT channel authorization (unconfirmed).
- assembly -shortest flag risk (monitoring).

## Completed (recent)
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
