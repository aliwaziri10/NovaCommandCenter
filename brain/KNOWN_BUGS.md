# Nova Command Center - Known Bugs

## Fixed

### Default Edge TTS voice was AriaNeural (female), not GuyNeural (male) as documented (fixed 2026-08-09)
narrate.py and narration_agent.py both defaulted `EDGE_TTS_VOICE` to `en-US-AriaNeural`, and narrate.yml had no override — so this default is what actually ran in production since the Edge TTS revert, despite every brain doc (ARCHITECTURE.md, PROJECT_STATE.md, SESSION_LOG.md) documenting `en-US-GuyNeural` as Nova's voice. Found during a full architecture/bug audit. Fixed in both files; confirmed committed.

### 73 consecutive Assemble workflow failures - moviepy KeyError on missing fps metadata (fixed 2026-08-08, confirmed 2026-08-09)
`assemble.py`'s `_get_video_duration()` used moviepy's `VideoFileClip`, which parses ffmpeg's probe output for a `video_fps` field and raises `KeyError` when that field is absent. This happened specifically on files produced by the script's own `ffmpeg -f concat -c copy` step earlier in the same run — stream-copy concat can leave fps metadata in a form moviepy's regex doesn't recognize. Crashed 73 consecutive runs (2026-08-06 to 2026-08-08) at this exact line, after every real step (block rendering, concat, audio mix) had already succeeded — the wasted-work pattern that made this especially costly. Fixed by reading duration straight from ffmpeg's own text output ("Duration: HH:MM:SS.ms") via regex instead of going through moviepy at all. No new failure issues since the fix landed (21:12 UTC 2026-08-08) as of this check.

### No proactive stuck/failure alert system (addressed 2026-08-09)
ARCHITECTURE.md previously noted: "There is no proactive stuck/failure alert system — permanently stalled videos must be found via direct Supabase queries." Added a new `supervisor.yml` GitHub Actions workflow (runs every 30 min) that checks every video's real DB state, force-triggers the correct pipeline stage via `workflow_dispatch` if it's been stuck past a normal cron window, auto-closes workflow-failure issues that predate a later fix commit to that same script, and opens one clearly-labeled "NEEDS HUMAN" issue (not repeat spam) if a video/stage has been force-retried 3 times with no progress. Complements, does not replace, the existing in-process `supervisor_agent.py` (which drives the pipeline forward but never detected or escalated stalls on its own).

### No content-policy recovery path for video clip generation (fixed 2026-08-09, confirmed committed and live)
`generate_videos.py` had no retry path when Agnes rejected a shot with `content_policy_violation` — the shot just failed permanently. Marius's `video_generation.py` had already solved this (its content_flagged videos were traced to ethnicity/genocide/war-crime terms in shot descriptions, common in WWII/historical-conflict content — the same territory Nova's channel covers). Ported the same approach: on a content-policy rejection, strip a fixed list of flagged terms from the shot description and retry once before giving up. CONFIRMED via direct GitHub read: `CONTENT_POLICY_STRIP_TERMS` and the retry logic in `_submit_clip` are live in `generate_videos.py`.

### narrate.yml installed stale Chatterbox deps after code reverted to Edge TTS (fixed 2026-08-09)
narrate.py and narration_agent.py were reverted from Chatterbox back to Edge TTS on 2026-08-09 (Chatterbox's only live run, 2026-08-08, produced ~4s of audio for a ~555s script — near-total synthesis failure). narrate.yml's pip install step was never updated to match — still installed chatterbox-tts/torchaudio, never installed edge-tts, guaranteeing a ModuleNotFoundError on every run. Fixed: narrate.yml now installs edge-tts pydub requests. Confirmed working via manual workflow run.

### Two Script rows contained a placeholder string instead of real content (fixed for both, confirmed 2026-08-09)
scripts.content for videos bf465973 (Voynich) and 6dc13529 (Silk Road) literally read "Script generation failed on part 1 — try running this task again." — leftover corruption from before the 2026-08-08 fix in script_writing_agent.py (which now raises instead of saving a placeholder). This also meant narrate.py's auto-select logic kept skipping both videos, because audio_path was still set to old ~40KB Chatterbox near-empty files that returned HTTP 200 (auto-select only checks liveness, not duration).
- bf465973: fully cleaned up — Video row, Script row, and 4 orphaned Task rows deleted; topic c5def7c7 reset to "researched" to regenerate cleanly.
- 6dc13529: real script content written directly into scripts.content (manually authored, matching the topic and channel's narration style) since this video already has 101 real generated clips and a real production_plan that must NOT be regenerated. audio_path cleared, narration re-run, and CONFIRMED SUCCESSFUL 2026-08-09: storage.objects shows the real file at 4.5MB (was ~40KB before). Video now fully ready for assembly.

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

### YouTube channel authorization confirmed correct (resolved 2026-07-19, structurally reconfirmed 2026-08-04)
Root cause was never credentials — it was OAuth Playground defaulting to the wrong Google identity (personal "Zia Waziri" instead of the "Awesome Amazing Unbelievable" Brand Account that owns Alternate Earth) during token generation. Fixed by explicitly selecting the Brand Account when authorizing. Reconfirmed structurally 2026-08-04: youtube_upload.py verifies the authorized channel title is "Alternate Earth" BEFORE any upload and hard-refuses otherwise — so any successful upload structurally proves the token is correct, no separate OAuth check needed.

## Unresolved / needs verification

- **.env.example does not exist in this repo at all** (not just uncommitted — never created). config.py's `database_url` still defaults to `sqlite:///./data/nova.db`. Harmless as long as Render's real DATABASE_URL env var is always set, but a silent landmine if that var is ever missing/misspelled.
- **production_plan duplication root cause** — see Fixed section above; only the symptom was cleaned up, not the mechanism.
- **Shot-line parsing is inconsistent across scripts**: generate_videos.py and asset_generation_agent.py (used by supervisor_agent.py for pipeline routing) only match lines starting with the literal word "Shot". assemble.py and narrate.py also accept bare numbered lines ("1.", "1)"). Currently harmless because video_planning_agent.py's prompt strictly enforces "Shot N:" only, but if that format ever drifts, different scripts will disagree on total_shots and the pipeline can silently stall or mis-time shots.
- **asset_generation_agent.py confirmed NOT dead code** (was flagged unverified in ARCHITECTURE.md) — supervisor_agent.py actively imports its `_parse_shots()` helper for pipeline routing. Its own image-generation function (`run_asset_generation`, Pollinations stills) does look orphaned — no router calls it that could be found; worth confirming next time this area is touched.
- **generate_images.py was never actually deleted** — still present in .github/scripts/, despite the 2026-07-25 session log claiming it was removed as dead code. generate_video_agnes.yml (flagged safe-to-delete since July) also still present, still untouched.
- **ACE_MUSIC_API_KEY** is declared as a secret in assemble.yml's env but is not referenced anywhere in assemble.py — looks like a dead/unused secret or a planned feature that was never built.
- **Long-video audio/video length mismatch risk**: appears to already be handled in assemble.py via a `tpad` freeze-frame pad when the video track is shorter than narration — not yet confirmed on a real end-to-end run, worth watching once 6dc13529 assembles.
- **Supervisor workflow (supervisor.yml) not yet observed in a real run** — added 2026-08-09, logic not yet battle-tested against a genuine stuck video or a genuinely stale issue.

## Rule
Every new bug (and its fix, once resolved) gets logged here immediately — including changes pushed directly by Ali outside a Claude session.
