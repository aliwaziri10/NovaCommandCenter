# Nova Command Center - Task Queue

## NEXT, in order (first written 2026-10-06 ~07:35 UTC, updated ~07:50 UTC — re-verify each before acting; see PROJECT_STATE.md "NEXT PROFILE START HERE" for the evidence)
1. **Learn GitHub's real answer to the Render server's workflow-start request.** DONE (code): commit `968b362` makes `trigger_workflow` raise with the real HTTP status and body. WAITING: Render must redeploy it, and a Render-side trigger must fail once more. Then read the reason from `tasks.payload->>'error'` (needs the database) or, without the database, from the "Last error" section of the next `Supervisor gave up: narration/video_clips/... ` issue on GitHub (the supervisor opens one after 2 failures). Fastest no-code alternative: Zia reads Render dashboard > Nova service > Logs and searches for `failed to trigger`.
2. **Fix the Render-side key `GITHUB_PAT` once the real status is known.** UNPROVEN hypotheses: it lacks "Actions: Read and write" on `aliwaziri10/NovaCommandCenter` (HTTP 403), or it expired (HTTP 401). It worked for creating issues (#206-#210) through Oct 2. Fix = Zia creates a new fine-grained token for that repo with Actions and Issues "Read and write", then replaces `GITHUB_PAT` in Render > Environment (Render redeploys on save). Give ONE step at a time with copy boxes.
3. ~~Check whether the scheduled workflows are running~~ — ANSWERED 2026-10-06: yes. Pipeline report #129 regenerated 03:45 UTC; `supervisor.yml` force-triggered narrate for both videos at 06:46 UTC (#211, #212); `narrate.yml` runs #400 and #401 both green. A ~1.6 h gap (00:34-02:12 UTC) remains unexplained, low priority.
4. ~~Verify the Outremer video row exists~~ — ANSWERED: video `af34e8f7` exists, at the narrate stage (issue #211). Still check its `videos` row in the database for `audio_path`.
5. **Verify narration really saved audio** for `574f10af` and `af34e8f7` (`videos.audio_path` not null; needs the database — the Supabase connector was refusing at ~07:45 UTC, probably needs a new chat or re-connecting). A green workflow run alone does not prove it.
6. **Watch that the burn loop stopped:** topic count in `topics` should not keep climbing now that script_writing works.
7. **Then, and only then, drain the dead backlog 1-2 items at a time** (about 35 topics with no script and about 8 scripts with no video had >=2 failed tasks): `delete from tasks where agent_name='script_writing' and status='failed' and payload->>'topic_id'='<id>'` (topics) or `agent_name='video_planning' ... payload->>'script_id'='<id>'` (scripts). Verify the deleted-row count each time. Each video_planning run blocks the free server about 5-7 minutes. Afterwards close the stale "Supervisor gave up ... gemini-2.5-pro 404" GitHub issues (#206-#210 and older).
8. Update `ARCHITECTURE.md` if the token or workflow wiring changes.

## In Progress
- Drain the ~36-script `draft` backlog through `video_planning`. 3 scripts (`2cc6415c`, `680cbc04`, `0fd0a844`) had their failed-task history cleared this session (already done by Zia via another profile before this check) but had not yet been picked up by the supervisor as of 2026-09-03 — follow up to confirm they actually progress on the next cycle(s), not just that they're eligible again. (2026-10-06: see NEXT item 7 above; planning itself is confirmed working.)
- Verify the newly-added `cinematographer_agent.py` stage (deployed 2026-09-03, sits between `video_planning` and `video_clips`). 2026-10-06: confirmed working on video `574f10af` (`cinematography_done = true`); clip generation after it not yet observed because the Render-side trigger for it is suspect (NEXT items 1-2).
- Verify the 2026-09-03 YouTube description fix (`youtube_upload.py`, commit `a4faad67`) on a real post-fix upload — confirm the description is genuinely per-video (from script_content), not the old generic fallback.

## Next (older items, still open)
- **Create `PIPELINE_LOCK.md`** — referenced by `HARD_CONSTRAINTS.md` ("check PIPELINE_LOCK status before pushing pipeline code") but does not exist anywhere in the repo. Confirmed via full `brain/` directory listing 2026-09-03. Either build the file/mechanism it implies, or remove the reference from HARD_CONSTRAINTS.md if it's no longer the intended workflow.
- Re-check whether the 2026-09-02 "backend unreachable" report (issue #129) was a one-off free-tier cold-start (current working theory, unconfirmed) or something recurring — if it happens again, treat it as a real pattern, not noise.
- ~~Confirm why no new script has been written since 2026-08-29 16:18 UTC~~ — ANSWERED 2026-10-06: Google retired `gemini-2.5-pro`; fixed in commit `35263a9`.
- **UNVERIFIED - freeze-frame fix.** Zia reported on 2026-08-23 that video `446872f6` (created 2026-08-16, predates the chain-extension freeze-frame fix `e5effeef` from 2026-08-23) froze mid-video. Not yet confirmed whether a genuinely post-fix video still freezes. Check a video generated after 2026-08-23 specifically before concluding either way.
- Confirm .env.example — it does not exist in this repo at all (not just uncommitted). Create it with the Supabase DATABASE_URL (used only for the Postgres DB now, never storage — see PROJECT_STATE.md), replacing config.py's stale SQLite default.
- Decide whether to unify shot-line parsing across scripts (generate_videos.py/asset_generation_agent.py accept only "Shot N:"; assemble.py/narrate.py also accept bare numbered lines) — currently harmless but a latent inconsistency.
- Decide whether to delete generate_images.py and generate_video_agnes.yml — both flagged as dead/unused since July but never actually removed (last checked 2026-08-09, not re-verified since).
- Confirm ACE_MUSIC_API_KEY (secret in assemble.yml) is actually unused, or find where it's supposed to be used.
- Minor: `strategy_research` fails because `YOUTUBE_API_KEY` is not set.
- Never verified: 1080p waxy-skin fix; Edge TTS narration end to end.

## Known Bugs
See KNOWN_BUGS.md for the full log. Newly added 2026-10-06:
- script_writing 404 on retired `gemini-2.5-pro` (FIXED, commit `35263a9`, confirmed with a real run).
- Render-side `GITHUB_PAT` cannot start workflows (OPEN; real HTTP reason not yet known; `trigger_workflow` now reports it since commit `968b362`).
- Scheduled GitHub Actions automation: confirmed running 2026-10-06 (answered).

Added 2026-09-03:
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
- 2026-10-06: `trigger_workflow` now reports GitHub's real HTTP status/body when it fails (commit `968b362`, mock-tested, file verified byte-identical to the tested copy).
- 2026-10-06: Fixed script_writing (commit `35263a9`): Google retired `gemini-2.5-pro` (HTTP 404 on every task since 2026-09-05). Primary model is now `gemini-3.1-pro-preview`, with fallback to `gemini-3.5-flash` on 429 or any non-retryable error. Confirmed with a real run: script `2f00da18` written 2026-10-06 00:24 UTC (1345 words, 6 chapters).
- 2026-10-06: Confirmed video_planning (gemini-3.5-flash) and cinematography work on real data (video `574f10af`); Outremer video `af34e8f7` exists; `narrate.yml` runs #400/#401 succeeded when started by `supervisor.yml`.
- 2026-10-06: Reset the failed-task rows for one dead topic (`84cb1398`) and one dead script (`0bea9075`) as a live test; both progressed.
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
