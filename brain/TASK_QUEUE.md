# Nova Command Center - Task Queue

## In Progress
- Drain the ~36-script `draft` backlog through `video_planning`. 3 scripts (`2cc6415c`, `680cbc04`, `0fd0a844`) had their failed-task history cleared this session (already done by Zia via another profile before this check) but had not yet been picked up by the supervisor as of 2026-09-03 — follow up to confirm they actually progress on the next cycle(s), not just that they're eligible again.
- Verify the newly-added `cinematographer_agent.py` stage (deployed 2026-09-03, sits between `video_planning` and `video_clips`) actually processes a real video end-to-end without regressing the pipeline — not yet observed on a real run.
- Verify the 2026-09-03 YouTube description fix (`youtube_upload.py`, commit `a4faad67`) on a real post-fix upload — confirm the description is genuinely per-video (from script_content), not the old generic fallback.

## Next
- **Create `PIPELINE_LOCK.md`** — referenced by `HARD_CONSTRAINTS.md` ("check PIPELINE_LOCK status before pushing pipeline code") but does not exist anywhere in the repo. Confirmed via full `brain/` directory listing 2026-09-03. Either build the file/mechanism it implies, or remove the reference from HARD_CONSTRAINTS.md if it's no longer the intended workflow.
- Re-check whether the 2026-09-02 "backend unreachable" report (issue #129) was a one-off free-tier cold-start (current working theory, unconfirmed) or something recurring — if it happens again, treat it as a real pattern, not noise.
- Confirm why no new script has been written since 2026-08-29 16:18 UTC — plausibly the supervisor deprioritizing new script_writing while the 36-script backlog sits unprocessed at video_planning, but not confirmed either way. Read supervisor_agent.py's task-selection logic directly if this keeps being true after the backlog drains.
- **UNVERIFIED - freeze-frame fix.** Zia reported on 2026-08-23 that video `446872f6` (created 2026-08-16, predates the chain-extension freeze-frame fix `e5effeef` from 2026-08-23) froze mid-video. Not yet confirmed whether a genuinely post-fix video still freezes. Check a video generated after 2026-08-23 specifically before concluding either way.
- Confirm .env.example — it does not exist in this repo at all (not just uncommitted). Create it with the Supabase DATABASE_URL (used only for the Postgres DB now, never storage — see PROJECT_STATE.md), replacing config.py's stale SQLite default.
- Decide whether to unify shot-line parsing across scripts (generate_videos.py/asset_generation_agent.py accept only "Shot N:"; assemble.py/narrate.py also accept bare numbered lines) — currently harmless but a latent inconsistency.
- Decide whether to delete generate_images.py and generate_video_agnes.yml — both flagged as dead/unused since July but never actually removed (last checked 2026-08-09, not re-verified since).
- Confirm ACE_MUSIC_API_KEY (secret in assemble.yml) is actually unused, or find where it's supposed to be used.

## Known Bugs
See KNOWN_BUGS.md for the full log. Newly added this session:
- PIPELINE_LOCK.md referenced but doesn't exist (see above).
- Nova's YouTube description was always the generic fallback, never per-video, since nothing populates video.description — fixed 2026-09-03 (commit `a4faad67`), not yet verified on a real upload.
- constraint_gate.yml never actually checked `protected_files`/`required_if_protected_file_touched` despite `constraints.json` defining them — fixed 2026-09-03, verified live.

Carried over, still unresolved as of last check (2026-08-09, not re-verified this session):
- .env.example missing entirely / config.py stale SQLite default.
- production_plan duplication root cause (symptom fixed, mechanism unknown).
- Shot-line parsing inconsistency across scripts.
- asset_generation_agent.py's image-generation path possibly dead code.
- generate_images.py / generate_video_agnes.yml never actually deleted.
- ACE_MUSIC_API_KEY unused.

## Completed (recent)
- 2026-09-03: Fixed Nova's YouTube description bug (generic fallback on every upload, confirmed via Zia comparing Nova vs Marius Studio side by side) — ported Marius's per-video description pattern. Commit `a4faad67`.
- 2026-09-03: Fixed constraint_gate.yml gap (issue #143) — protected_files/required_if_protected_file_touched were defined but never checked. Applied via GitHub web editor (workflows-scope 403 blocks direct write), verified live.
- 2026-09-03: Confirmed Render backend healthy/Live (not crashed, despite issue #129's "unreachable" report) via direct dashboard check.
- 2026-09-03: Confirmed "Gemini returned nothing usable" video_planning failures are transient/self-healing on retry (script bb4c81be failed once, succeeded 40 min later on its own) — not a systemic Gemini outage.
- 2026-09-03: Corrected stale PROJECT_STATE.md claim that GitHub write access is blocked (403) for Claude — confirmed working for regular files this session via multiple successful pushes; only `.github/workflows/*.yml` remains genuinely blocked (missing `workflows` scope).
- 2026-09-02 (per README.md, not a Claude session): Media storage fully migrated from Supabase Storage to Backblaze B2 — Supabase Free's 50MB global file-size hard cap made CRF20 1080p renders (600-750MB) impossible to store there.
- 2026-09-03 (per commit history, not this session): New `cinematographer_agent.py` pipeline stage added between video_planning and video_clips.
- 2026-08-09: Full architecture audit, Edge TTS voice bug fixed (was silently AriaNeural, docs said GuyNeural), several stale KNOWN_BUGS.md entries corrected.

## Rule
Every new task or bug goes here immediately — including anything pushed directly to GitHub outside a session.
