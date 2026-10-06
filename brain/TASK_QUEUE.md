# Nova Command Center - Task Queue

## NEXT, in order (written 2026-10-06 ~07:35 UTC — re-verify each before acting; see PROJECT_STATE.md "NEXT PROFILE START HERE" for the evidence)
1. **Unblock narration for video `574f10af`** (it failed to trigger `narrate.yml` twice and is abandoned at MAX_RETRIES=2). First learn GitHub's real answer. Two ways:
   - Fast, no code: Zia opens the Render dashboard > Nova service > Logs and searches for `trigger` (the line printed by `github_actions_client.trigger_workflow`); paste the HTTP status/message.
   - Permanent: patch `backend/app/agents/github_actions_client.py` (small file) so `trigger_workflow` RAISES `RuntimeError` containing the real HTTP status and response body instead of returning False. Every caller (`supervisor_agent.py` narration branch, `tasks_router.py` generate_videos branch) already raises on False, so only the saved task error text changes. Push only when no task is running (a push restarts Render and cuts a running task off). Then delete the 2 failed `narration` task rows for video `574f10af` (`payload->>'video_id'`) and press run-now.
2. **Fix the cause once the real status is known.** UNPROVEN hypothesis: the server's GitHub token (env var name is in `github_actions_client.py`) is missing, expired, or lacks "Actions: Read and write" on `aliwaziri10/NovaCommandCenter`. Only act on this if the real status is 401/403/404.
3. **Check whether the scheduled workflows are really running:** GitHub Actions tab > "Keep Backend Awake" (`keep-alive.yml`, cron */10) and "Supervisor" (`supervisor.yml`, cron */30): enabled? latest run status? Also `select * from tasks where created_at > '2026-10-06 02:16+00' order by created_at` to see whether any automatic cycle ran after Zia's last manual press. A ~1.6 h gap with no tasks (00:34 to 02:12 UTC) while script `2f00da18` needed planning is the only evidence so far.
4. **Verify the Outremer video row exists** for script `2f00da18` (its `video_planning` task completed 02:16 UTC; only the task row was checked, not the `videos` row).
5. **Watch that the burn loop stopped:** topic count in `topics` should not keep climbing now that script_writing works.
6. **Then, and only then, drain the dead backlog 1-2 items at a time** (about 35 topics with no script and about 8 scripts with no video had >=2 failed tasks): `delete from tasks where agent_name='script_writing' and status='failed' and payload->>'topic_id'='<id>'` (topics) or `agent_name='video_planning' ... payload->>'script_id'='<id>'` (scripts). Verify the deleted-row count each time. Each video_planning run blocks the free server about 5-7 minutes.
7. If the Supabase connector still returns "FGA Authentication Error. Unauthorized" (seen twice ~07:35 UTC), ask Zia to reconnect it.
8. Update `ARCHITECTURE.md` if the token or workflow wiring changes.

## In Progress
- Drain the ~36-script `draft` backlog through `video_planning`. 3 scripts (`2cc6415c`, `680cbc04`, `0fd0a844`) had their failed-task history cleared this session (already done by Zia via another profile before this check) but had not yet been picked up by the supervisor as of 2026-09-03 — follow up to confirm they actually progress on the next cycle(s), not just that they're eligible again. (2026-10-06: see NEXT item 6 above; planning itself is confirmed working.)
- Verify the newly-added `cinematographer_agent.py` stage (deployed 2026-09-03, sits between `video_planning` and `video_clips`). 2026-10-06: confirmed working on video `574f10af` (`cinematography_done = true`); clip generation after it not yet observed because narration is blocked.
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
- Narration cannot trigger `narrate.yml` (OPEN, real HTTP reason not yet known).
- Scheduled GitHub Actions automation: unknown whether it is driving the pipeline (OPEN, unverified).

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
- 2026-10-06: Fixed script_writing (commit `35263a9`): Google retired `gemini-2.5-pro` (HTTP 404 on every task since 2026-09-05). Primary model is now `gemini-3.1-pro-preview`, with fallback to `gemini-3.5-flash` on 429 or any non-retryable error. Confirmed with a real run: script `2f00da18` written 2026-10-06 00:24 UTC (1345 words, 6 chapters).
- 2026-10-06: Confirmed video_planning (gemini-3.5-flash) and cinematography work on real data (video `574f10af`).
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
