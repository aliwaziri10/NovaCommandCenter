# HARD CONSTRAINTS — Nova / Alternate Earth

READ THIS FILE BEFORE TOUCHING ANY PIPELINE CODE. This is not a suggestion doc —
`.github/workflows/constraint_gate.yml` runs on every push and checks the real
diff against `constraints.json` in this same folder. A violation fails the
check with a red X on the commit and opens a GitHub Issue automatically. It
does not silently pass.

## Current locked decisions (as of 2026-08-20)

1. **Visual style: full black-and-white cinematography is the CONFIRMED,
   DELIBERATE target.** This is a deliberate Zia decision (retention/hook
   strategy), not a bug. DO NOT revert to color. DO NOT reintroduce "vivid
   saturated color" / "no desaturation" language into `QUALITY_GUARD` or any
   prompt-building code. Sepia/vintage-film/old-aged looks are still banned —
   the target is modern, high-contrast monochrome, not an old-film filter.
2. **Shorts are permanently OFF** for this channel. Do not add Shorts pipeline
   logic (separate short-form workflow, vertical export, <60s target) without
   Zia explicitly reopening this in writing.
3. **No paid tools / no billing on this account, ever**, until $5,000 revenue
   is reached. No API keys requiring a card on file. No paid tiers of Agnes,
   Render, Supabase, or any other service used here.
4. **CapCut is banned** (illegal in India). Clipchamp is the only approved
   assembly tool if manual assembly is ever needed.
5. **Higgsfield is permanently excluded** from this pipeline.

## How to change one of these

Only Zia can change a locked decision, and only by saying so explicitly in a
session. When that happens, the session making the change MUST update both
this file and `constraints.json` in the same commit that changes the code —
never leave the gate enforcing a stale rule.

## For any session (Claude or otherwise) starting work here

1. Read this file.
2. Read `constraints.json` (same folder) — that's what the gate actually checks.
3. Before pushing any change to a pipeline file (`.github/scripts/*.py`,
   `backend/app/agents/*.py`), check `PIPELINE_LOCK` status in Supabase
   (see `brain/PIPELINE_LOCK.md`) — do not push a change while a run is
   mid-flight on the file you're touching.
