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
- Nova will be migrated from gTTS to Chatterbox TTS (matching Marius) — see TASK_QUEUE.md. Decision made, not yet implemented.
- `/brain` restructured: three files required by `INDEX.md` (`ARCHITECTURE.md`, `KNOWN_BUGS.md`, `SESSION_LOG.md`) existed only in name, never in content — this was the root cause of stale/contradictory project state across sessions. All six files in `INDEX.md`'s read order now actually exist and are kept current. The old ad-hoc `NOTES.md` file (which duplicated and contradicted `PROJECT_STATE.md`) is deleted — `/brain` is the only source of truth going forward.

## Rule
Every significant decision must be added here with its reason. Historical entries about decommissioned infrastructure (e.g. the old Railway hosting) are not kept — once something is fully replaced, its rationale stops being useful and is removed rather than archived.
