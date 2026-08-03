# Nova Command Center - Session Log

## 2026-08-04
- Investigated: a video published the day before started narrating raw Python source partway through instead of the script.
- Found `script_writing_agent.py` already had a same-day-prior fix (2026-08-03) rejecting code/markup before saving a script — but `narration_agent.py` had no equivalent defense of its own.
- Fixed: added a code/markup rejection guard directly in `narration_agent.py`.
- Reviewed all 8 files in `backend/app/agents/` end to end (topic_research, script_writing, video_planning, narration, asset_generation, assembly, supervisor, strategy_research, github_actions_client). No other code-leak vectors found. Flagged assembly's `-shortest` ffmpeg flag as a risk worth watching now that videos are long-form.
- Confirmed Nova is still on plain gTTS — the Chatterbox TTS port (used successfully in Marius) was discussed previously but never implemented. Added to TASK_QUEUE.md as next priority.
- Restructured `/brain`: `ARCHITECTURE.md`, `KNOWN_BUGS.md`, `SESSION_LOG.md` (required by INDEX.md's read order but never created) now exist. Purged all Railway references from `PROJECT_STATE.md`, `TASK_QUEUE.md`, `DECISIONS.md` — Railway is fully decommissioned and no longer part of this project's tracked history. Deleted the old ad-hoc `NOTES.md`, which duplicated and contradicted `PROJECT_STATE.md`.
- Root-caused the bad video via direct Supabase query: video "The Hidden Code" (Voynich Manuscript topic), script id `1b31fbc5`, created 2026-07-17 — over two weeks before the Aug 3 fix existed. A Cloudflare 502 HTML error page from Pollinations got saved as the second half of the script verbatim, then narrated as-is. The script sat unused until 2026-08-01 when video_planning finally picked it up, by which point today's narration guard didn't exist yet either.
- User deleted the video from YouTube. Video row `04f9a0ab` and corrupted script row `1b31fbc5` both deleted from Supabase (confirmed 0 rows remaining for both). The "Voynich Manuscript" topic (`c5def7c7`) was left in `research` status so the supervisor naturally regenerates a clean script for it, this time protected by both the 2026-08-03 and 2026-08-04 fixes.

## Rule
Append one entry per session, before ending it. Never edit past entries — only add new ones.
