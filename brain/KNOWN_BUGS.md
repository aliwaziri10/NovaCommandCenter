# Nova Command Center - Known Bugs

## Fixed

### narrate.yml installed stale Chatterbox deps after code reverted to Edge TTS (fixed 2026-08-09)
narrate.py and narration_agent.py were reverted from Chatterbox back to Edge TTS on 2026-08-09 (Chatterbox's only live run, 2026-08-08, produced ~4s of audio for a ~555s script — near-total synthesis failure). narrate.yml's pip install step was never updated to match — still installed chatterbox-tts/torchaudio, never installed edge-tts, guaranteeing a ModuleNotFoundError on every run. Fixed: narrate.yml now installs edge-tts pydub requests. Confirmed working via manual workflow run.

### Two Script rows contained a placeholder string instead of real content (fixed for one of two, 2026-08-09)
scripts.content for videos bf465973 (Voynich) and 6dc13529 (Silk Road) literally read "Script generation failed on part 1 — try running this task again." — leftover corruption from before the 2026-08-08 fix in script_writing_agent.py (which now raises instead of saving a placeholder). This also meant narrate.py's auto-select logic kept skipping both videos, because audio_path was still set to old ~40KB Chatterbox near-empty files that returned HTTP 200 (auto-select only checks liveness, not duration).
- bf465973: fully cleaned up — Video row, Script row, and 4 orphaned Task rows deleted; topic c5def7c7 reset to "researched" to regenerate cleanly.
- 6dc13529: real script content written directly into scripts.content (manually authored, matching the topic and channel's narration style) since this video already has 101 real generated clips and a real production_plan that must NOT be regenerated. audio_path cleared on both videos so narrate.yml would pick them up. Re-run initiated 2026-08-09 — confirm result at start of next session (check storage.objects for narration/6dc13529... file size; should be well over 1MB if real, not ~40KB).

### production_plan duplicated across two unrelated videos (partially fixed 2026-08-09 — root cause still unknown)
bf465973 (Voynich) and 6dc13529 (Silk Road) had byte-for-byte identical production_plan content (md5-verified) and both had 101 real clips generated against it, despite being unrelated topics. Content-matched the plan against both topics' notes (boardroom/trade-negotiation imagery, "present day" arc) and concluded it genuinely belongs to 6dc13529 — bf465973 was carrying a duplicate with no topical connection. video_planning_agent.py generates production_plan fresh from script.content per call with no code path that copies between videos — HOW the duplication happened is unresolved. Worth a close read of video_planning_agent.py's Video row creation logic, and Supabase's created_at ordering for both rows, next time this is touched. Low urgency now that bf465973 is wiped and the real pairing (6dc13529) is confirmed, but this could recur for a future video pair.

### Stray duplicate migration file from GitHub web-editor mistake (fixed 2026-08-09)
backend/alembic/versions/backend/alembic/versions/003_add_audio_path_to_videos.py — a nested-path artifact from 2026-07-02, when the full relative path was typed into the "new file" box while already inside backend/alembic/versions/. Harmless to Alembic (non-recursive scan) but confusing in the file tree. Deleted; confirmed via fresh directory listing. Full repo swept recursively afterward — no other instances of this pattern found anywhere.

### Delete Video endpoint crashed with 500 — missing DB column (fixed 2026-08-04)
character_reference_url was added to Video model on 2026-08-03 but no migration was ever run against Supabase. Fixed by adding the column live plus migration 006.

### Narration spoke raw code/markup instead of the script (fixed 2026-08-04)
narration_agent.py had no defense against bad script content reaching TTS. Fixed with the same guard already in script_writing_agent.py.

### Script generation accepted malformed AI output as valid script text (fixed 2026-08-03)
Fixed with _looks_like_code_or_markup() in script_writing_agent.py.

### video_planning silently failed forever after Pollinations endpoint retirement (fixed 2026-07-29)
text.pollinations.ai retired in favor of gen.pollinations.ai/text.

## Unresolved / needs verification

- **.env.example and config.py's database_url default still reference sqlite:///./data/nova.db**, stale since the July Postgres/Supabase migration. Harmless as long as Render's real DATABASE_URL env var is always set, but a silent landmine if that var is ever missing/misspelled — migrations could silently target a throwaway SQLite file instead of erroring. Fix given to Ali for .env.example specifically; NOT YET CONFIRMED COMMITTED.
- **production_plan duplication root cause** — see Fixed section above; only the symptom was cleaned up, not the mechanism.
- **YouTube channel authorization**: still unconfirmed whether YT_REFRESH_TOKEN targets "Alternate Earth" vs "Erased" — needs a live OAuth Playground check or real upload test.
- **Long-video audio/video length mismatch risk**: assembly_agent.py's ffmpeg -shortest flag trims to whichever of (video, narration) is shorter — not yet confirmed to have caused a real truncation, but worth watching now that 6dc13529's narration length won't exactly match its original planned shot durations (narrate.py auto-scales shot_durations to fit real narration length, so this should self-correct, but worth confirming on this video specifically once it assembles).

## Rule
Every new bug (and its fix, once resolved) gets logged here immediately — including changes pushed directly by Ali outside a Claude session.
