# Nova Command Center - Known Bugs

## Fixed

### Narration spoke raw code/markup instead of the script (fixed 2026-08-04)
`script_writing_agent.py` was patched 2026-08-03 to reject code/HTML/JSON garbage from Pollinations before saving it as a script. But `narration_agent.py` had zero defense of its own — it would TTS whatever was in `script.content` with no check. Any script saved before the 2026-08-03 fix, or reaching narration through any future code path, was unprotected. Fixed by adding the same rejection guard directly inside `narration_agent.py`, so narration defends itself instead of trusting script_writing to have already done it.

### Script generation accepted malformed AI output as valid script text (fixed 2026-08-03)
Old fallback logic accepted any response over 100 characters as valid script text, including raw HTML error pages, JSON fragments, or code from a degraded/erroring Pollinations API call. Fixed with `_looks_like_code_or_markup()` in `script_writing_agent.py`.

### video_planning silently failed forever after Pollinations endpoint retirement (fixed 2026-07-29)
`text.pollinations.ai` was retired in favor of `gen.pollinations.ai/text`. Every video_planning call failed silently and the supervisor kept rescheduling the same doomed task instead of surfacing it as broken — no new video was planned for 6 days.

## Unresolved / needs verification
- **YouTube channel authorization**: chat history claims `YT_REFRESH_TOKEN` was fixed to target "Alternate Earth" instead of "Erased", but nothing in this repo confirms it. Needs a live OAuth Playground check or a real test upload before being trusted.
- **Long-video audio/video length mismatch risk**: `assembly_agent.py` uses ffmpeg's `-shortest` flag when muxing narration audio with the assembled silent video, which trims to whichever is shorter. Now that Nova targets longer-form videos, a shot-duration/narration-length mismatch could silently cut a video short or truncate narration. Not yet confirmed to have happened — watch for it.

## Rule
Every new bug (and its fix, once resolved) gets logged here immediately.
