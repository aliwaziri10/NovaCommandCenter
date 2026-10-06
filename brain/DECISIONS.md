# Nova Command Center - Decisions

## Purpose
Record important technical and business decisions so future sessions understand why they were made.

## Decisions

### 2026-07-08
- Agnes API requests are sent sequentially to avoid HTTP 429 rate limits.
- Progress is saved after every generated clip.
- Never rely on chat history. The /brain folder is the single source of truth for project memory.

### 2026-08-04
- Content direction: Nova now produces long-form videos, not short ~30s clips.
- `/brain` restructured: three files required by `INDEX.md` (`ARCHITECTURE.md`, `KNOWN_BUGS.md`, `SESSION_LOG.md`) existed only in name, never in content — this was the root cause of stale/contradictory project state across sessions. All six files in `INDEX.md`'s read order now actually exist and are kept current. The old ad-hoc `NOTES.md` file (which duplicated and contradicted `PROJECT_STATE.md`) is deleted — `/brain` is the only source of truth going forward.

### 2026-08-09
- Nova was migrated from gTTS to Chatterbox TTS (2026-08-03/04), then reverted back to Edge TTS the same day (2026-08-09) after Chatterbox's only live run produced near-total synthesis failure. Edge TTS (en-US-GuyNeural) is the confirmed, final choice — not a placeholder, not still pending.

### 2026-10-06
- **Script-writing model: Zia chose "Option B" — Google's suggested newer Pro model first, with automatic fallback to Flash.** `script_writing_agent.py` now uses `GEMINI_MODEL_PRIMARY = "gemini-3.1-pro-preview"` and `GEMINI_MODEL_FALLBACK = "gemini-3.5-flash"` (commit `35263a9`). Reason: `gemini-2.5-pro` was retired by Google (HTTP 404 on every script_writing task since 2026-09-05), and Google's own error named `gemini-3.1-pro-preview` as the replacement. The fallback now also fires on 404/400/401/403 from the primary, not just 429, so a retired or disallowed model costs one wasted call instead of killing script generation. Option A (Flash only) was offered and NOT chosen; it remains the safe default if the preview model proves unusable on the free key. Caveat: it is a "-preview" model and can be retired the same way 2.5-pro was.
- Standing business rule from Zia: no spending until the business makes $5,000; free tools only.

## Rule
Every significant decision must be added here with its reason. Historical entries about decommissioned infrastructure (e.g. the old Railway hosting) are not kept — once something is fully replaced, its rationale stops being useful and is removed rather than archived.
