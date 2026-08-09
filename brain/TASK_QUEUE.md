# Nova Command Center - Task Queue

## In Progress
- None currently blocking. `6dc13529` (Silk Road video) is fully ready for assembly (101/101 clips, 101/101 shot_durations, real 4.5MB narration audio confirmed) - waiting on the assemble stage to run. NEXT SESSION: confirm it actually reached status=assembled and check final video quality (lighting, sync, no truncation).

## Next
- Confirm .env.example — it does not exist in this repo at all (not just uncommitted). Create it with the Supabase DATABASE_URL, replacing config.py's stale SQLite default.
- Investigate HOW bf465973 and 6dc13529 ended up with byte-identical production_plan content — see KNOWN_BUGS.md.
- Confirm the new supervisor.yml workflow's first live runs behave as expected (force-triggers, auto-closes, escalation) — not yet observed in a real run.
- Confirm the content-policy-retry in generate_videos.py fires on a real historical-conflict shot (code confirmed live 2026-08-09, just not yet triggered for real).
- Decide whether to unify shot-line parsing across scripts (generate_videos.py/asset_generation_agent.py accept only "Shot N:"; assemble.py/narrate.py also accept bare numbered lines) — currently harmless but a latent inconsistency. See KNOWN_BUGS.md.
- Confirm whether asset_generation_agent.py's run_asset_generation() (Pollinations still-image generation) is actually called from anywhere, or whether it's dead weight now that _parse_shots is the only part of that file still used (by supervisor_agent.py).
- Decide whether to delete generate_images.py and generate_video_agnes.yml — both flagged as dead/unused since July but never actually removed.
- Confirm ACE_MUSIC_API_KEY (secret in assemble.yml) is actually unused, or find where it's supposed to be used — currently declared but never referenced in assemble.py.

## Known Bugs
See KNOWN_BUGS.md for the full log — unresolved items only:
- .env.example missing entirely / config.py stale SQLite default.
- production_plan duplication root cause (symptom fixed, mechanism unknown).
- Shot-line parsing inconsistency across scripts (see above).
- asset_generation_agent.py's image-generation path possibly dead code.
- generate_images.py / generate_video_agnes.yml never actually deleted.
- ACE_MUSIC_API_KEY unused.
- Supervisor workflow (supervisor.yml) unobserved in a real run.

## Completed (recent)
- 2026-08-09: Full architecture audit (all 6 brain files + every pipeline script/workflow/agent read directly from GitHub). Found and fixed a real production bug: Edge TTS voice was silently AriaNeural instead of documented GuyNeural — fixed in narrate.py and narration_agent.py, confirmed committed. Corrected 3 stale "unresolved" KNOWN_BUGS.md entries that were actually already fixed (YouTube channel auth, content-policy retry, audio/video length mismatch). Confirmed asset_generation_agent.py is NOT dead code (imported by supervisor_agent.py). Confirmed generate_images.py was never actually deleted despite an earlier session log claiming so.
- 2026-08-09: Confirmed 6dc13529's re-narration succeeded (4.5MB real audio file) - fully unblocked and ready for assembly.
- 2026-08-09: Root-caused and confirmed the fix for 73 consecutive "Assemble workflow failed" issues.
- 2026-08-09: Built and committed a new Supervisor workflow (supervisor.yml + supervisor.py).
- 2026-08-09: Ported Marius's content-policy retry fix into generate_videos.py - confirmed committed and live.
- 2026-08-09: Fixed narrate.yml stale Chatterbox deps (now installs edge-tts).
- 2026-08-09: Found and deleted stray duplicate migration file.
- 2026-08-09: Cleaned up bf465973 (Voynich) — deleted corrupted Video/Script rows + 4 orphaned tasks, topic reset to regenerate.
- 2026-08-09: Diagnosed production_plan duplication between bf465973 and 6dc13529.
- 2026-08-09: Wrote real narration script directly for 6dc13529 (Silk Road).
- 2026-08-04: Fixed missing character_reference_url column (migration 006).
- 2026-08-04: Added defensive code/markup guard to narration_agent.py.
- 2026-08-03: script_writing_agent.py patched to reject code/markup/JSON garbage.
- 2026-07-29: Fixed dead Pollinations text endpoint.
- 2026-07-15: Backend migration to Render completed and verified.

## Rule
Every new task or bug goes here immediately — including anything pushed directly to GitHub outside a session.
