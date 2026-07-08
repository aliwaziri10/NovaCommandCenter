# Nova Command Center - Decisions

## Purpose
Record important technical and business decisions so future sessions understand why they were made.

## Decisions

### 2026-07-08
- Agnes API requests are sent sequentially to avoid HTTP 429 rate limits.
- Progress is saved after every generated clip.
- Never rely on chat history.
- The /brain folder is the single source of truth for project memory.

## Rule
Every significant decision must be added here with its reason.
