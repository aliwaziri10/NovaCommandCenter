# Nova Rebuild — Style Overhaul Handoff

## Why this file exists
A prior session proposed a full rewrite of Nova's storytelling/visual format (20-item list, see "Full Item List" below). That session was interrupted mid-task before anything was committed except one stray comment fix. This doc is the real, GitHub-verified status — do not trust chat history or any other handoff doc for this specific initiative.

## Rule for this initiative
One item at a time. After each item is committed, verify it by re-fetching from GitHub, mark it done below, then move to the next. Do not batch multiple items into one commit.

## Full Item List (source of truth for what "done" means)
1. Curiosity Loop as master structure (6 fixed beats, resolve gradually)
2. Hook-Problem-Solution-Payoff spine (hook 0-30s, stakes 30s-25%, delivery 25-85%, payoff final 15%)
3. Cold open at most dramatic moment, then cut back
4. Front-loaded value line, no channel intro before it
5. Best moment at ~70% mark, not the very end
6. New music cue/shift at every chapter/emotional turn
7. **Full-motion B&W video per shot — DONE (2026-08-19)**
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

## Status

### DONE
- **#7 Full-motion B&W** — `.github/scripts/generate_videos.py`, `QUALITY_GUARD` constant rewritten to enforce black & white cinematography (was "vivid saturated color", explicitly banned desaturation). Committed and verified against GitHub 2026-08-19. Deliberately not sepia/vintage-filter — full grayscale motion cinematography.

### NOT STARTED (verified — no trace in repo as of 2026-08-19)
All items above except #7. In particular #1, #2, #3, #4, #10, #12, #14 all live in `script_writing.py` (need to locate exact path — likely `backend/agents/script_writing.py` or similar; confirm before editing) and have not been touched.

## Recommended next step
Item #4 (front-loaded value line, no "hey guys" intro) and #14 (drop "you are standing in" narration voice) are the smallest, most isolated changes in script_writing.py — good next single-task pick, before tackling the larger Curiosity Loop structural rewrite (#1/#2/#3/#10 together, since they're structurally intertwined).

## Rules carried over from PROJECT_STATE.md (still apply)
- GitHub write access for Claude is intermittently 403 on this repo — always confirm before assuming a push succeeded; deliver as full-file copy-paste + direct /edit/main/ link when it fails.
- Read all files in /brain before starting work; this repo is the single source of truth, not chat history.
- Do not reference Railway anywhere in new writing (RAILWAY_URL env var name is legacy-only, do not rename).

## Last Updated
2026-08-19
