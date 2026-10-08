# HANDOFF 2026-10-08: visual quality, narration pacing, YouTube Agent Skill ports

Written by Claude for Zia. Read this first, then verify live before acting (Zia's rule: no claim about system state without a fresh lookup in the same session). Zia is non-technical: click-by-click steps, full-file replacements, every copyable value in its own code block.

This same file is pushed to both repos:
- Marius (Erased): `aliwaziri10/marius-command-center`, file at repo root
- Nova (Alternate Earth): `aliwaziri10/NovaCommandCenter`, file at `brain/`

## 1. Done today (verified by commit)

| What | Repo | Commit | Status |
|---|---|---|---|
| B2 presigned-URL fix. Agnes failed every shot-2+ anchor with "Download image URL failed: 403"; 66 scripts stalled. Presign now uses the region parsed from the endpoint, fetches 1 byte to prove the URL works, returns None (no anchor) if refused | Marius `scripts/storage_b2.py` | `bdec309` | Pushed. Cause (wrong signing region) is strongly indicated, NOT confirmed by a live run. Check the next Video Generation log for "not fetchable" or "WITHOUT an image anchor". If seen, check the B2 key permissions next |
| Narration pacing: rate -5% to +6%, pauses 1-2s to 0.35-0.5s, fragments under 5 words merged into the previous sentence, ellipsis no longer ends a sentence | Marius `scripts/narration.py` | `3238ca1` | Pushed, not yet listened to |
| Narration pacing: slowdown 0.95 to 1.0, rate variation +4..+8%, pauses 1.0s to 0.4s, same merge and ellipsis fixes | Nova `.github/scripts/narrate.py` | `0efdb2f` | Pushed, not yet listened to |
| Supabase data (Marius): 66 stalled scripts reset to `images_generated`; then 73 scripts with `video_next_index` 0 or 1 reset to `pending` (video_urls cleared, narration_url and shot_durations nulled) for re-narration at 1 per run | Marius database | n/a | Done. 3 scripts far into video generation (14, 14, 24 clips) were left alone |

Not done: Nova's already-narrated videos still have the old slow audio. Nova's database is on Render, not Supabase, so it was not checked.

## 2. Problems Zia reported on 2026-10-08 (all still OPEN)

1. Faces look waxy.
2. The protagonist is in almost every picture.
3. Faces morph: one person turns into another person inside a clip or between clips.
4. There is no check that catches morphing or bad planning; if a plan or clip is bad it should be redone automatically.
5. Narration voice itself (Microsoft Guy via edge-tts). The Qwen3-TTS "Ryan" plan was decided on 2026-09-04 and NEVER built; both channels still run edge-tts.

## 3. Evidence gathered (Marius only)

- MEASURED: across 45 Marius scripts from the last 14 days, the single most common `primary_subject` covers on average 79% of shots (range 67% to 83%).
- CODE FACT: `scripts/prompt_builder.py`, `build_agnes_prompt()`, puts the full `setting_and_characters` text (which describes the recurring protagonist) at the front of EVERY level-0 prompt. It is only stripped for shots whose description contains crowd or group keywords, and dropped on the fallback tiers. So even a shot about a landscape or a document gets the protagonist described.
- The planner prompt in `scripts/shot_breakdown_stage.py` (around line 1069) already contains a "REAL DOCUMENTARY BALANCE - THE STORY IS NOT JUST THE PROTAGONIST" rule, and each shot has a `primary_subject` tag. Nothing enforces either one after planning.
- Anti-waxy and anti-morphing wording has been in the prompts since 2026-09-10 (positive and negative). It did not solve the problem, so prompt wording alone is not the fix.
- Nova: NOT inspected for the same anchor behaviour. Check `.github/scripts/generate_videos.py` and `brain/ARCHITECTURE.md` (it describes character-reference image for shot 0, then each clip chained to the previous clip's last frame).

## 4. Build list (in this order)

### 4.1 Plan check: protagonist cap (planning stage)
- After the shot breakdown, count shots per `primary_subject`. Hard-reject and re-plan if the top subject is over a cap. PROPOSAL: 40% of shots. Needs Zia's eye on the first results.
- Also reject plans where the same named character appears in two consecutive shots more than twice in a row.
- Where: end of `scripts/shot_breakdown_stage.py` validation (it already has hard-rejection helpers).

### 4.2 Prompt fix: only describe the protagonist when the shot is about them
- In `build_agnes_prompt()`, if the shot's `primary_subject` is not the protagonist, send only the setting, era and palette part of the anchor, not the character description. Needs the anchor split into "world" and "character" parts at planning time, or a simple sentence filter like `_strip_named_characters_for_group_shot()`.

### 4.3 Clip check: morphing and waxy-face detector (after each clip, before upload to B2)
NOT built, NOT tested. Two options; build option A first:
- A) Vision-model check. Sample 4 to 6 frames per clip, send them to a vision model (Gemini free tier is already used elsewhere in this pipeline; use the existing `llm_client.py` pattern), ask for JSON: same person across frames yes/no, face deformation yes/no, waxy skin yes/no, score 0-10. Fail below a threshold.
- B) Local check with OpenCV or ONNX face embeddings: detect faces in frames every 0.5s, compare embedding distance across frames of the same track; a jump means a different person. Heavier on the free GitHub runner; verify runtime first.
- On fail: regenerate the shot with a new seed (max 2 tries), then fall back to a shot with no visible face (wide, hands, objects, landscape, back view). Log every rejection to Supabase so the rate can be measured.
- Waxy skin extra idea (HYPOTHESIS, untested): light film grain and slight sharpening at assembly time hides the smooth look. Test on one clip before rolling out.

### 4.4 Measure
- Add a per-script report line: top-subject percentage, clips rejected, clips regenerated. Compare with the 79% baseline above.

## 5. YouTube Agent Skill: what to take

Source (public, MIT licence, keep the licence notice when copying code):

```
https://github.com/Jakeschincariol/youtube-agent-skill
```

Zia was looking for a repo of his own with that name. None exists under `aliwaziri10`, `Wazzaboyzz` or `adrian001234`; the repo above is the one that was read. If Zia gives a different link, read that one instead.

It is built for people filming themselves, not for AI documentaries, so only part applies. Nothing in it detects faces or morphing; section 4 must be built separately.

| Take | File in that repo | Our use |
|---|---|---|
| Hook scorer (5 properties, weakest-link weighting) and 21 hook formulas | `skills/yt-script/hookscore.py`, `hooks.json` | Gate in script writing: write 5 openings, score, keep top 2, redo if low. The author says it is a rough guide calibrated on short-form hooks, not a prediction |
| Title and thumbnail linter: title under 60 characters (40 on mobile), thumbnail 3 words or fewer and not repeating the title, a number or name in the title, at most 2 all-caps words | `skills/yt-package/title.py` | Gate before upload in both `youtube_upload.py` files; addresses click-through |
| Retention reader | `skills/yt-retention/retention.py` | After a video is live, Zia exports the retention file from YouTube Studio; Claude reads it and adjusts script prompts. Manual export for now |
| Chapter builder that follows YouTube's rules | `skills/yt-chapters/chapters.py` | Auto chapters in every description, built from our shot timings |
| SEO, Shorts, outlier ranking | `skills/yt-seo`, `yt-shorts`, `yt-viral` | Later: better descriptions, a Shorts format, topic research |
| Skip | `yt-edit`, `yt-comment`, `voice.md` | Talking-head or human-voice tools; not a fit |

Port order: title linter, hook scorer, chapters, then the rest.

## 6. First things the next session should do

1. Read the latest Marius Video Generation run log. Look for "not fetchable" or "WITHOUT an image anchor" (B2 fix check).
2. Query Marius Supabase: count scripts by status; confirm no new `video_stalled`.
3. Read the first re-narrated Marius video's audio length and listen to a sample with Zia.
4. Start section 4.1 and 4.2 (cheap, no new services), then 4.3.
5. Check Nova for the same anchor and protagonist behaviour before changing it.
6. Never run tests locally for Zia; use GitHub Actions. Deliver full files with the GitHub edit URL.
