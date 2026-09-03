# Nova Rebuild — Style Overhaul Handoff

## Why this file exists
A prior session proposed a full rewrite of Nova's storytelling/visual format (20-item list, see "Full Item List" below). This doc is the real, GitHub-verified status. **Earlier versions of this file went stale repeatedly** (most recently: it listed #6/#9 as "not started" after they'd already shipped) — treat any status doc, including this one, as unverified until cross-checked against the actual source files.

## Rule for this initiative
One item at a time. After each item is committed, verify it by re-fetching from GitHub, mark it done below, then move to the next. Do not batch multiple items into one commit.

## Full Item List (source of truth for what "done" means)
1. Curiosity Loop as master structure (6 fixed beats, resolve gradually)
2. Hook-Problem-Solution-Payoff spine (hook 0-30s, stakes 30s-25%, delivery 25-85%, payoff final 15%)
3. Cold open at most dramatic moment, then cut back
4. Front-loaded value line, no channel intro before it
5. Best moment at ~70% mark, not the very end
6. New music cue/shift at every chapter/emotional turn
7. Full-motion B&W video per shot
8. Visual/camera-angle variation at least every 40 seconds
9. Specific numbers/facts at a steady rate throughout
10. Chapter markers baked into every script from generation
11. Ending recontextualizes the opening line/scene
12. No "in summary / to wrap up" language
13. Series/universe framing (recurring intro sting, consistent visual identity)
14. Drop the second-person "you are standing in" narration voice
15. Verified-facts research gate before scripting
16. Niche-gap check before committing a topic
17. Consistent upload cadence (1-2x/week) over peak polish
18. Retention-graph feedback loop from YouTube Analytics
19. End screen bridging directly into next video's hook
20. Guardrail against photorealistic named historical figures

## Status (verified live against script_writing_agent.py, generate_videos.py, assemble.py, youtube_upload.py, 2026-09-03)

### DONE — 12 of 20
- **#1 Curiosity Loop 6-beat structure** — `script_writing_agent.py`, Rule 0 + matching part1/part2 prompt instructions.
- **#2 Hook-Problem-Solution-Payoff spine** — same file, mapped explicitly onto the 6 beats in Rule 0.
- **#3 Cold open, then cut back** — Rule 0B, with an explicit bridge-line requirement.
- **#4 No channel-greeting intro before value line** — Rule 1, explicit ban on "hey guys"/"welcome back" etc.
- **#5 Peak "wow" moment at ~70% mark** — Rule 9, placed inside the CLIMAX beat specifically, distinct from PAYOFF.
- **#6 New music cue at every chapter/emotional turn** — `assemble.py`, `_build_music_bed()` + `_MUSIC_CHAPTERS` (6 mood-matched Kevin MacLeod/incompetech CC-BY tracks, one per story beat, crossfaded at chapter boundaries). Required attribution is added unconditionally to every video's YouTube description by `youtube_upload.py`'s `MUSIC_ATTRIBUTION_LINE` (confirmed live 2026-09-03 - a stale comment in assemble.py claiming this was still outstanding was corrected same session).
- **#7 Full-motion B&W video** — `generate_videos.py`, `QUALITY_GUARD` rewritten to enforce grayscale cinematography (deliberately not sepia/vintage-filter).
- **#8 Camera-angle variation every 40s** — `generate_videos.py`, time-bucketed on real elapsed runtime (`CAMERA_VARIATION_INTERVAL_SECONDS`), not shot count. Confirmed live 2026-09-03.
- **#9 Steady numbers/facts throughout** — Rule 8, spread across both part1/part2 prompts, not just the opening.
- **#10 Chapter markers from generation** — Rule 0C, `[CHAPTER: ...]` markers for all 6 beats, distinct from `[SCENE]` markers. Also independently reconstructed at upload time in `youtube_upload.py` from real shot_durations if the script-side markers are unavailable.
- **#12 No "in summary" language** — Rule 7 + explicit instruction in part2_prompt's ending beat.
- **#14 Drop "you are standing in..." narration** — Rule 4, explicit ban alongside guidance on what direct-address forms remain allowed.

### NOT STARTED — 8 of 20, no trace in any pipeline file as of 2026-09-03
#11, #13, #15, #16, #17, #18, #19, #20

## Recommended next step
Of the remaining 8, #15 (verified-facts research gate) and #16 (niche-gap check) are pre-production/content-quality gates - highest leverage for avoiding wasted renders on a bad topic. #11 (ending recontextualizes opening) and #20 (no photorealistic named historical figures - a real likeness/liability risk, unlike the others which are purely stylistic) are prompt/script changes similar in scope to what's already shipped. #13, #17, #18, #19 are more structural/operational (channel identity, cadence discipline, analytics feedback loop, end-screen linking) and depend on data Nova doesn't yet expose (e.g. #18 needs YouTube Analytics API integration, not just a prompt change).

## Rules carried over from PROJECT_STATE.md (still apply)
- GitHub write access for Claude was intermittently 403 on this repo through 2026-08-09; retested working (direct push succeeded, no 403) as of 2026-09-03 - always confirm before assuming a push will succeed either way.
- Read all files in /brain before starting work; this repo is the single source of truth, not chat history.
- Do not reference Railway anywhere in new writing (RAILWAY_URL env var name is legacy-only, do not rename).

## Last Updated
2026-09-03 (corrected — verified against live generate_videos.py, assemble.py, youtube_upload.py, not carried forward from the 2026-08-19 version which had gone stale on #6, #9, #8's true status)
