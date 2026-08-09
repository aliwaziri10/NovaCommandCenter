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

## Rule
Every significant decision must be added here with its reason. Historical entries about decommissioned infrastructure (e.g. the old Railway hosting) are not kept — once something is fully replaced, its rationale stops being useful and is removed rather than archived.
