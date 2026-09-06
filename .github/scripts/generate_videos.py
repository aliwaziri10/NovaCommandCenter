"""
Nova Command Center - Video Generation Agent

[... all prior docstring history unchanged through 2026-09-04 named-figure
likeness guardrail ...]

UPDATED (2026-09-06): DARK-SCREEN / WESTERN-LIKENESS / ANACHRONISM FIX,
PORTED FROM MARIUS'S CONFIRMED-LIVE prompt_builder.py.

Zia flagged three recurring bugs on 4 published Nova videos. Instead of
guessing new guard wording for Nova in isolation, this checks what
Marius's equivalent file (scripts/prompt_builder.py, confirmed live)
actually does differently, since Marius's darkness bug was already
root-caused and fixed there on 2026-08-22.

MARIUS'S CONFIRMED ROOT CAUSE (2026-08-22 LIGHTING FIELD FIX comment,
verbatim from prompt_builder.py): "two conflicting lighting instructions
in one prompt was the confirmed cause of daytime shots rendering
dark/underlit." Marius's fix was NOT new lighting wording - it was
PROMPT POSITION. Their lighting cue is placed LAST in the assembled
prompt, on the documented principle that "a single negative-instruction
block stated once early in a long combined prompt is known to lose
weight the further it sits from the end of the prompt" (see
ANACHRONISM_GUARD_SHORT's comment in the same file) - i.e. the
instruction closest to the end has the most authority with the video
model, and lighting sat too early to win against everything after it.

Nova's prompt builder had this backwards: LIGHTING_DIRECTIVE was placed
FIRST in _build_prompt(), before QUALITY_GUARD/ANACHRONISM_GUARD/the
actual shot description - the least authoritative position possible.
Fix: lighting cue moved to run LAST, immediately before camera_move/
lens_style, matching Marius's proven position exactly. QUALITY_GUARD's
"deep blacks/high contrast monochrome" phrasing is also removed (still
a real self-contradiction against "bright" even before the reorder) in
favor of bright high-key grayscale language, matching how Marius's own
QUALITY_GUARD stays purely about clarity/color-science and leaves all
brightness/exposure claims to the lighting cue alone, not fighting it.

ANACHRONISM: Marius runs ANACHRONISM_GUARD once early AND repeats a
SHORT form of it again immediately after visual_description, for the
same recency-authority reason - "repeated in short form immediately
after visual_description (recency-authority positioning)". Ported here
as ANACHRONISM_GUARD_SHORT, appended right after the shot description,
with vehicle/infrastructure terms (trucks, motorcycles, paved roads,
power lines, signage) added to the full guard that weren't there before.

CULTURAL ACCURACY (Aurangzeb rendering as a Western man on a European
chair): Marius has no direct equivalent (different content domain), so
this one guard is genuinely new to Nova, not ported. Given the same
recency-authority evidence from Marius's own fixes, it is likewise
placed late in the prompt (right after the shot description, alongside
the repeated anachronism guard) rather than bundled into the early guard
block where Nova's other guards already sit.
"""

import os
import re
import sys
import time

import requests

RAILWAY_URL = os.environ["RAILWAY_URL"]  # points to Render, kept as RAILWAY_URL for compatibility
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()
AGNES_API_KEY = os.environ["AGNES_API_KEY"]

AGNES_BASE = "https://apihub.agnes-ai.com/v1"
AGNES_VIDEO_URL = f"{AGNES_BASE}/videos"
AGNES_IMAGE_URL = f"{AGNES_BASE}/images/generations"
AGNES_POLL_URL = "https://apihub.agnes-ai.com/agnesapi"
# CHANGED (2026-09-07): raised from 768x1152 (Agnes's 720p tier) to true
# 1080p (1920x1080 landscape, per Agnes's docs normalization table) - Ali
# flagged skin going waxy/plastic on both Nova and Marius. Agnes's own
# docs confirm output is over-smoothed most aggressively at low
# resolution before their upsampler runs, so this is being tried first,
# before any negative_prompt change.
CLIP_HEIGHT = 1080
CLIP_WIDTH = 1920
CLIP_FRAME_RATE = 24
MIN_FRAMES = 49    # ~2s floor, matches Marius
# FREEZE-PAD FIX (2026-08-19, Phase 2b - see module docstring): was 169
# (~7.04s ceiling). Raised to 241 (~10.04s, still a valid 8n+1 frame
# count) so narration-driven shot durations landing just past the old
# cap no longer get silently truncated and freeze-padded at assembly.
MAX_FRAMES = 241   # ~10s ceiling (was 169/~7s) - see FREEZE-PAD FIX note above
# CHAIN-EXTENSION FIX (2026-08-23, Phase 3 - see module docstring):
# shots needing more than MAX_FRAMES now chain up to this many real
# Agnes segments instead of freeze-padding everything past the first one.
MAX_CHAIN_SEGMENTS = 4
DEFAULT_SHOT_SECONDS = 5.0  # only used if shot_durations is unavailable for this video
MAX_WAIT_SECONDS = 240
POLL_INTERVAL_SECONDS = 10
MIN_SECONDS_BETWEEN_SUBMITS = 10  # FIX (2026-08-13): was 4 - too tight, let content-policy retry bursts trip real 429s
AGNES_IMAGE_MAX_RETRIES = 3
CONTENT_POLICY_RETRY_SPACING_SECONDS = 20  # FIX (2026-08-13): was 5 - too tight, see module docstring
CAMERA_VARIATION_INTERVAL_SECONDS = 48  # item #8: guarantee a genuinely different camera move at least this often, keyed to real elapsed runtime

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "20"))

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)
HEADERS = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}

CAMERA_MOVES = [
    # CHANGED (2026-08-26): rebalanced away from constant fast/rapid/sweeping/
    # urgent/dramatic energy - most entries now calm and steady, slow motion
    # added as its own category, only a few dynamic entries kept (not
    # deleted, just a smaller share of the rotation). Also renamed the
    # "drone-style" entry to "aerial" - the literal word "drone" was
    # contradicting ANACHRONISM_GUARD's "no drones" in the same prompt and
    # was the likely cause of drones appearing on-screen.
    "gentle aerial push-in",
    "smooth tracking shot alongside the subject",
    "subtle low-angle tilt up",
    "slow motion, gentle drift, dreamlike weight to the movement",
    "slow dramatic zoom with parallax",
    "steady tracking shot, calm and grounded",
    "gentle crane shot rising over the scene",
    "tight composed close-up with shallow depth of field",
    "slow motion tracking shot, weighty and deliberate",
    "sweeping crane shot rising over the scene",
    "fast tracking shot alongside the subject, urgent energy",
    "dramatic low-angle tilt up",
]

LENS_STYLES = [
    "shot on 35mm anamorphic lens, shallow depth of field, subtle lens flare",
    "shot on vintage 50mm prime lens, soft natural bokeh, warm film tone",
    "wide-angle lens, deep focus, expansive epic framing",
    "telephoto compression, soft background blur, natural motion blur",
]

# CHANGED (2026-09-06, see module docstring): kept the bright/evenly-lit
# wording, but this now runs LAST in the assembled prompt (see
# _build_prompt below) instead of first - ported from Marius's confirmed
# 2026-08-22 fix, where lighting sitting too early was the actual root
# cause of dark output, not the wording itself.
LIGHTING_DIRECTIVE = (
    "bright, clearly and evenly lit scene, strong daylight or warm well-lit "
    "interior lighting, high visibility, no heavy shadows, no underexposed or "
    "murky darkness, no dark filter or overlay, no vignette or darkened frame "
    "edges, no low-key lighting, no day-for-night look, exposure reads as "
    "bright and clear even in black and white, whites and midtones clearly "
    "visible throughout, nothing shrouded in shadow or haze"
)

# CHANGED (2026-09-06): added vehicle/infrastructure terms (trucks,
# motorcycles, paved roads, power lines, modern signage) not previously
# listed. Still runs early in the prompt, same as before.
ANACHRONISM_GUARD = (
    "historically accurate to this exact time period and setting, no modern technology, "
    "no cars, no trucks, no motorcycles, no drones, no modern clothing, no digital devices, "
    "no anachronistic objects of any kind, no laptops, no computers, no smartphones, no tablets, "
    "no screens or monitors of any kind, no modern furniture, no electrical wiring or outlets, "
    "no plastic objects, no paved asphalt roads, no power lines or utility poles, no modern "
    "signage or printed text, no wristwatches, no synthetic fabrics, no modern eyewear"
)

# ADDED (2026-09-06, ported from Marius's ANACHRONISM_GUARD_SHORT):
# repeated in short form immediately after the shot description (see
# _build_prompt), on Marius's confirmed principle that a negative
# instruction stated once early in a long prompt loses weight the
# further it sits from the end - this is what actually gets obeyed.
ANACHRONISM_GUARD_SHORT = (
    "strictly no cars, no trucks, no motorcycles, no drones, no laptops, no computers, "
    "no smartphones, no tablets, no screens or monitors of any kind, no modern technology "
    "of any kind, no modern equipment of any era but this one"
)

# ADDED (2026-09-04, rebuild item #20 - see module docstring
# "NAMED-HISTORICAL-FIGURE LIKENESS GUARDRAIL"): applied to every prompt,
# same as the other guards below. Narration is allowed (and, per
# script_writing_agent.py Rule 12, required) to name real historical
# figures - this guard only affects what the VIDEO model is told to
# render when a shot description happens to include one of those names.
NAMED_FIGURE_GUARD = (
    "if this scene depicts a specific real named historical individual, "
    "do not attempt a specific, identifiable likeness of that real person - "
    "render them as a generic, unidentifiable period-appropriate person instead "
    "(via framing, distance, angle, silhouette, obscured or turned-away face, or "
    "similar composition choices), never a recognizable portrait of the actual "
    "historical figure; still include the person and the action described, just "
    "without attempting their real likeness"
)

# ADDED (2026-09-06, see module docstring "CULTURAL ACCURACY"): no Marius
# equivalent exists (different content domain) - genuinely new to Nova.
# Placed late in the prompt (right after the shot description, alongside
# ANACHRONISM_GUARD_SHORT) on the same recency-authority evidence, rather
# than bundled into the early guard block where it would lose weight the
# same way lighting did.
CULTURAL_ACCURACY_GUARD = (
    "every person and setting in this scene must visually match the actual culture, "
    "ethnicity, and civilization the story is set in - never default to a generic "
    "Western/European appearance, costume, or furniture style; for example, if the "
    "scene is set in the Mughal Empire, any Mughal ruler such as Aurangzeb must be "
    "depicted as a South Asian man in period-accurate Mughal royal attire (jama, "
    "turban, jewels) seated on a low ornate Mughal-style gaddi or throne with bolster "
    "cushions, never a Western man in a European high-backed chair; apply the same "
    "rule to every civilization and region a shot is set in - correct ethnicity, "
    "correct traditional dress, correct throne, seating, or architecture style for "
    "that exact culture and time period"
)

# CHANGED (2026-08-19): style overhaul phase 1. Full-motion black & white
# is now the enforced look. Deliberately NOT "sepia" or "vintage film" -
# real full-motion grayscale cinematography with genuine walking, weather,
# fire, hands - not static pans, not a stylized old-film filter.
# CHANGED AGAIN (2026-09-06, see module docstring "DARK-SCREEN ...
# STRENGTHENING"): removed "deep blacks" and "high contrast monochrome" -
# that phrasing was contradicting LIGHTING_DIRECTIVE's "bright, evenly
# lit" instruction in the same prompt and was the most likely cause of
# scenes reading as dark even in explicit daylight settings. Now asks for
# bright, high-key grayscale instead of deep-black/high-contrast grayscale.
QUALITY_GUARD = (
    "full black and white cinematography, rich grayscale tonal range, bright high-key "
    "exposure, clean whites and soft readable mid-tones, gentle natural contrast, no deep "
    "crushed blacks, high-end digital cinema shot in black and white, crisp sharp clarity, "
    "professional monochrome color grading, shallow depth of field, cinematic lighting, "
    "no color of any kind, not sepia toned, not a vintage film filter, not a static "
    "photograph - full natural motion within the frame, no grainy degraded film look, "
    "no artificial CGI look, no flat synthetic AI look, no plastic skin"
)

MOTION_CONTINUITY_GUARD = (
    "movement in this shot is purposeful and matches what the scene actually calls for - "
    "the subject only walks, gestures, or moves if the action requires it, otherwise remains "
    "still or engaged in a static action (standing, sitting, working with hands); "
    "motion continues smoothly and continuously in the same direction and speed, "
    "no reversing, no snapping backward, no sudden stop-and-restart, no pausing mid-motion, "
    "no aimless or unmotivated walking"
)

DISTINCT_INDIVIDUALS_GUARD = (
    "every person visible in this shot is a distinct, unique individual with "
    "a different face, body, and clothing from every other person in the "
    "frame - never repeat or clone one character's likeness onto more than "
    "one person, even in a crowd, group, or background"
)

CONTENT_POLICY_STRIP_TERMS = [
    "genocide", "ethnic cleansing", "war crime", "war crimes", "atrocity", "atrocities",
    "massacre", "concentration camp", "death camp", "gas chamber", "holocaust",
    "extermination", "torture", "execution", "mass grave", "prisoner of war",
    "internment", "persecution", "purge", "ethnic", "racial",
]

CROWD_OR_GROUP_KEYWORDS = (
    "two ", "three ", "four ", "five ", "several", "group of", "crowd",
    "family", "villagers", "workers", "neighbors", "neighbours", "soldiers",
    "colleagues", "team", "both", "twins", "pair of", "everyone", "people",
    "others", "onlookers", "bystanders", "crew", "townspeople", "children",
)


def _sanitize_for_content_retry(description):
    sanitized = description
    for term in CONTENT_POLICY_STRIP_TERMS:
        sanitized = re.sub(re.escape(term), "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s{2,}", " ", sanitized).strip(" ,")
    return sanitized


class ContentPolicyRejection(Exception):
    pass


def round_to_valid_frames(num_frames):
    import math
    n = math.ceil((num_frames - 1) / 8)
    n = max(0, n)
    return 8 * n + 1


def _clean_shot_text(text):
    text = re.split(r"\*{0,2}Duration\*{0,2}\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"\bCamera\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]
    # FIX (2026-09-03, see module docstring "CINEMATOGRAPHY-LINE LEAK FIX"):
    # cinematographer_agent.py (2026-09-02) inserts a "Cinematography: <brief>"
    # line into each shot's text. Without stripping it here, that DP brief
    # rode along inside the parsed shot description and got sent to Agnes
    # as raw text, on top of this script's own independently-chosen
    # camera_move/lens_style for the same shot - a collision, not an
    # integration. Stripped here the same way Duration/Camera already are.
    text = re.split(r"\bCinematography\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = text.replace("**", "").replace("*", "").strip().rstrip(".").strip()
    return text


def _parse_shots(production_plan):
    # FIX PART 1 (2026-08-17): accumulate every line belonging to a shot
    # (inline text on the header line, plus any following lines) until
    # the next "Shot N:" marker or a blank line, instead of only ever
    # reading text on the header line itself.
    #
    # FIX PART 2 (2026-08-20): part 1 used "if current_parts:" as a proxy
    # for "we are currently inside a shot block", which breaks whenever a
    # header line has NO inline text (e.g. a bare "Shot 1:" alone, with
    # the description starting on the next line) - current_parts starts
    # empty in that case, so the very next content line (and every line
    # after it) was silently dropped, producing 0 parsed shots for the
    # entire plan. Confirmed live on videos 5ca6e41d and 446872f6, both
    # of which use exactly this bare-header format. Now tracks an
    # explicit in_shot boolean instead, so lines are captured correctly
    # whether or not the header line itself had inline text.
    shots = []
    current_parts = []
    in_shot = False

    def flush():
        nonlocal in_shot
        if current_parts:
            text = _clean_shot_text(" ".join(current_parts))
            if text:
                shots.append(text)
            current_parts.clear()
        in_shot = False

    for raw_line in production_plan.splitlines():
        line = raw_line.strip()

        if SHOT_START.match(line):
            flush()
            in_shot = True
            remainder = SHOT_START.sub("", line, count=1).strip()
            remainder = re.sub(r"^[\s:\-–\*]+", "", remainder)
            if remainder:
                current_parts.append(remainder)
            continue

        if not line:
            # blank line ends the current shot's description block
            flush()
            continue

        if in_shot:
            current_parts.append(line)

    flush()
    return shots


def _shot_target_seconds(video, shot_index, total_shots):
    shot_durations = video.get("shot_durations")
    if shot_durations and len(shot_durations) > shot_index:
        return max(float(shot_durations[shot_index]), 1.0)
    return DEFAULT_SHOT_SECONDS


def _find_next_video_needing_clips():
    for attempt in range(3):
        try:
            resp = requests.get(f"{RAILWAY_URL}/api/v1/videos", timeout=90)
            break
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise
            print(f"Backend not responding (likely waking from sleep), retrying in 20s (attempt {attempt + 1}/3)...")
            time.sleep(20)
    resp.raise_for_status()
    videos = resp.json()

    print(f"[auto-select] Backend returned {len(videos)} video(s) total. Evaluating each:")

    candidates = []
    for v in videos:
        vid = v.get("id")
        status = v.get("status")

        if status in ("assembled", "uploaded"):
            print(f"[auto-select] {vid} ({status}): SKIP - status is '{status}' (already published or assembled, not worth generating further clips for)")
            continue

        production_plan = v.get("production_plan")
        if not production_plan:
            print(f"[auto-select] {vid} ({status}): SKIP - no production_plan")
            continue

        shots = _parse_shots(production_plan)
        if not shots:
            print(f"[auto-select] {vid} ({status}): SKIP - production_plan present but 0 shots parsed from it")
            continue

        clip_urls = v.get("clip_urls")
        print(f"[auto-select] {vid} ({status}): clip_urls type={type(clip_urls).__name__}, raw={clip_urls!r}")

        if not isinstance(clip_urls, list):
            print(f"[auto-select] {vid} ({status}): SKIP - clip_urls is not a list (type={type(clip_urls).__name__}), treating as needing full regeneration is unsafe, flagging instead of guessing")
            continue

        filled = sum(1 for u in clip_urls if u)
        print(f"[auto-select] {vid} ({status}): {len(shots)} shots parsed, clip_urls length={len(clip_urls)}, filled={filled}")

        if filled < len(shots):
            print(f"[auto-select] {vid} ({status}): CANDIDATE - {len(shots) - filled} shot(s) missing")
            candidates.append(v)
        else:
            print(f"[auto-select] {vid} ({status}): SKIP - all {len(shots)} shots already filled")

    if not candidates:
        print("[auto-select] No candidates found after evaluating all videos.")
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    chosen = candidates[0]["id"]
    print(f"[auto-select] Chosen (earliest created_at among {len(candidates)} candidate(s)): {chosen}")
    return chosen


def build_character_reference_prompt(topic_title, opening_shot_description=None):
    # UNUSED as of 2026-08-16 (chaining removed) - left in place, dormant,
    # in case a future single-protagonist format wants chaining back.
    if opening_shot_description:
        scene_line = (
            f"character reference portrait for a documentary about: {topic_title}, "
            f"positioned within this exact opening scene: {opening_shot_description}"
        )
        pose_line = "captured mid-action within the scene, natural candid moment, not posed, not centered, clear face and clothing detail"
    else:
        scene_line = f"character reference portrait for a documentary about: {topic_title}"
        pose_line = "full figure visible, natural candid pose, clear face and clothing detail"

    parts = [
        scene_line,
        pose_line,
        LIGHTING_DIRECTIVE,
        QUALITY_GUARD,
        ANACHRONISM_GUARD,
    ]
    return ", ".join(p for p in parts if p)


def generate_character_reference(video_id, topic_title, opening_shot_description=None):
    # UNUSED as of 2026-08-16 (chaining removed) - left in place, dormant.
    prompt = build_character_reference_prompt(topic_title, opening_shot_description)
    last_error_text = None

    for attempt in range(AGNES_IMAGE_MAX_RETRIES):
        try:
            resp = requests.post(
                AGNES_IMAGE_URL,
                headers=HEADERS,
                json={
                    "model": "agnes-image-2.1-flash",
                    "prompt": prompt,
                    "size": f"{CLIP_WIDTH}x{CLIP_HEIGHT}",
                    "extra_body": {"response_format": "url"},
                },
                timeout=60,
            )
        except requests.RequestException as e:
            last_error_text = str(e)
            print(f"Character reference image request raised an exception (attempt {attempt + 1}/{AGNES_IMAGE_MAX_RETRIES}): {e}")
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            last_error_text = resp.text
            print(f"Character reference image transient error {resp.status_code} (attempt {attempt + 1}/{AGNES_IMAGE_MAX_RETRIES}): {resp.text}")
            time.sleep(10 * (attempt + 1))
            continue

        if resp.status_code >= 400:
            print(f"Character reference image generation failed permanently ({resp.status_code}): {resp.text} - continuing without one.")
            return None

        data = resp.json()
        image_url = None
        for entry in data.get("data", []):
            if isinstance(entry, dict) and entry.get("url"):
                image_url = entry["url"]
                break
        if not image_url:
            image_url = data.get("url")
        if not image_url:
            print(f"Character reference image response had no usable URL: {data} - continuing without one.")
            return None

        patch_resp = requests.patch(
            f"{RAILWAY_URL}/api/v1/videos/{video_id}",
            json={"character_reference_url": image_url},
            timeout=30,
        )
        patch_resp.raise_for_status()
        print(f"Character reference image generated and saved for video {video_id}.")
        return image_url

    print(f"Character reference image generation exhausted all retries ({last_error_text}) - continuing without one.")
    return None


def _download_file(url, dest_path):
    # ADDED (2026-08-23): chain-extension needs local copies of each
    # segment to stitch them together - see _generate_shot_clip().
    try:
        resp = requests.get(url, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 0:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return True
    except requests.RequestException:
        pass
    return False


def _extract_last_frame_url(video_url_of_clip, out_tag):
    # Was UNUSED as of 2026-08-16 (cross-shot chaining removed). Reused
    # as of 2026-08-23 for WITHIN-shot chain-extension (see module
    # docstring) - this does not reintroduce cross-shot anchoring, it
    # only links segments belonging to the same shot together.
    try:
        import numpy as np
        from PIL import Image
        from moviepy.editor import VideoFileClip

        tmp_video = f"/tmp/_anchor_src_{out_tag}.mp4"
        r = requests.get(video_url_of_clip, timeout=120)
        r.raise_for_status()
        with open(tmp_video, "wb") as f:
            f.write(r.content)

        clip = VideoFileClip(tmp_video)
        frame = clip.get_frame(max(clip.duration - 1 / CLIP_FRAME_RATE, 0))
        clip.close()
        img = Image.fromarray(frame)
        png_path = f"/tmp/_anchor_{out_tag}.png"
        img.save(png_path)

        with open(png_path, "rb") as f:
            upload_resp = requests.post(
                f"{RAILWAY_URL}/api/v1/upload/reference/{out_tag}",
                files={"file": (f"{out_tag}.png", f, "image/png")},
                timeout=60,
            )
        os.remove(tmp_video)
        os.remove(png_path)

        if upload_resp.status_code >= 400:
            print(f"Reference frame upload failed - status {upload_resp.status_code}: {upload_resp.text}")
            return None
        return upload_resp.json().get("url")
    except Exception as e:
        print(f"Could not extract/upload last frame for continuity anchor, continuing without it: {e}")
        return None


def _concat_segments(segment_paths, out_path):
    # ADDED (2026-08-23): stitches chain-extended segments (same shot,
    # continuous action, each anchored on the previous segment's last
    # frame) into one continuous clip. Straight concat (no crossfade) -
    # anchoring already makes the cut point visually continuous, unlike
    # assemble.py's cross-SHOT blocks which need a crossfade to hide a
    # hard scene change.
    try:
        from moviepy.editor import VideoFileClip, concatenate_videoclips
        clips = [VideoFileClip(p) for p in segment_paths]
        combined = concatenate_videoclips(clips, method="compose")
        combined.write_videofile(
            out_path, fps=CLIP_FRAME_RATE, codec="libx264", audio=True,
            audio_codec="aac", threads=2, preset="medium", verbose=False, logger=None,
        )
        combined.close()
        for c in clips:
            c.close()
        return True
    except Exception as e:
        print(f"Failed to concatenate chain segments: {type(e).__name__}: {e}")
        return False


def _upload_clip(tag, local_path):
    # ADDED (2026-08-23): uploads a stitched chain-extended clip to the
    # new /api/v1/upload/clip/{tag} backend endpoint (durable Supabase
    # Storage), returns the public URL to save into clip_urls.
    try:
        with open(local_path, "rb") as f:
            resp = requests.post(
                f"{RAILWAY_URL}/api/v1/upload/clip/{tag}",
                files={"file": (f"{tag}.mp4", f, "video/mp4")},
                timeout=180,
            )
        if resp.status_code >= 400:
            print(f"Chain-extended clip upload failed - status {resp.status_code}: {resp.text}")
            return None
        return resp.json().get("url")
    except Exception as e:
        print(f"Chain-extended clip upload raised an exception: {type(e).__name__}: {e}")
        return None


def _submit_clip_raw(prompt, num_frames, anchor_image_url=None):
    body = {
        "model": "agnes-video-v2.0",
        "prompt": prompt,
        "height": CLIP_HEIGHT,
        "width": CLIP_WIDTH,
        "num_frames": num_frames,
        "frame_rate": CLIP_FRAME_RATE,
    }
    if anchor_image_url:
        body["image"] = anchor_image_url

    try:
        submit = requests.post(AGNES_VIDEO_URL, headers=HEADERS, json=body, timeout=60)
    except requests.RequestException as e:
        return None, f"submit request error: {type(e).__name__}: {str(e)[:150]}", False

    if submit.status_code == 400 and "content_policy_violation" in submit.text:
        print(f"[content-policy] Agnes rejection body: {submit.text[:500]}")
        return None, f"content_policy_violation: {submit.text[:300]}", True
    if submit.status_code == 429:
        return None, "RATE LIMITED (429) — Agnes RPM exceeded, will retry next run", False
    if submit.status_code != 200:
        return None, f"submit failed: HTTP {submit.status_code}: {submit.text[:200]}", False

    data = submit.json()
    video_id = data.get("video_id") or data.get("id") or data.get("task_id")
    if not video_id:
        return None, f"no video_id/id/task_id in submit response: {data}", False
    return video_id, None, False


def _submit_clip(description, shot_index, num_frames, elapsed_seconds_before_shot=0.0, anchor_image_url=None):
    # item #8: camera move is bucketed by real elapsed runtime, not shot
    # index, so it's guaranteed to change at least every
    # CAMERA_VARIATION_INTERVAL_SECONDS regardless of shot count/length in
    # that window. lens_style stays index-keyed for intra-bucket variety.
    camera_bucket = int(elapsed_seconds_before_shot // CAMERA_VARIATION_INTERVAL_SECONDS)
    camera_move = CAMERA_MOVES[camera_bucket % len(CAMERA_MOVES)]
    lens_style = LENS_STYLES[shot_index % len(LENS_STYLES)]
    is_group_shot = any(kw in description.lower() for kw in CROWD_OR_GROUP_KEYWORDS)

    # CHANGED (2026-09-06, see module docstring): reordered to match
    # Marius's confirmed-live prompt structure. Early block is now only
    # the guards that are safe to state once, up front (quality/
    # anachronism/motion/named-figure). desc comes next, then the
    # recency-authority block (repeated short anachronism guard +
    # cultural accuracy guard - both new/repositioned here), then
    # LIGHTING_DIRECTIVE, then camera/lens LAST of all - lighting used to
    # run first (least authoritative slot); it now runs last (most
    # authoritative slot), exactly matching Marius's proven position.
    def _build_prompt(desc, include_camera=True):
        early_guards = [QUALITY_GUARD, ANACHRONISM_GUARD, MOTION_CONTINUITY_GUARD, NAMED_FIGURE_GUARD]
        if is_group_shot:
            early_guards.append(DISTINCT_INDIVIDUALS_GUARD)

        if not include_camera:
            parts = early_guards + [
                desc,
                ANACHRONISM_GUARD_SHORT,
                CULTURAL_ACCURACY_GUARD,
                LIGHTING_DIRECTIVE,
                "shot by a Hollywood cinematographer, steady centered composition, "
                "documentary style, realistic motion, high detail",
            ]
            return ", ".join(p for p in parts if p)

        parts = early_guards + [
            desc,
            ANACHRONISM_GUARD_SHORT,
            CULTURAL_ACCURACY_GUARD,
            LIGHTING_DIRECTIVE,
            f"shot by a Hollywood cinematographer, {camera_move}, {lens_style}",
            "steady, composed documentary style",
            "realistic motion, natural motion blur, high detail, controlled cinematic framing",
        ]
        return ", ".join(p for p in parts if p)

    agnes_video_id, error, was_content_policy = _submit_clip_raw(
        _build_prompt(description), num_frames, anchor_image_url
    )

    if was_content_policy:
        sanitized = _sanitize_for_content_retry(description)
        if sanitized and sanitized != description:
            print(
                f"Shot {shot_index}: content policy rejected original description, "
                f"retrying once with flagged terms stripped: {sanitized!r}"
            )
            time.sleep(CONTENT_POLICY_RETRY_SPACING_SECONDS)
            agnes_video_id, error, was_content_policy = _submit_clip_raw(
                _build_prompt(sanitized), num_frames, anchor_image_url
            )

        if was_content_policy and anchor_image_url:
            print(
                f"Shot {shot_index}: still content policy rejected with anchor image - "
                f"retrying once more WITHOUT the continuity anchor (text-to-video only)."
            )
            time.sleep(CONTENT_POLICY_RETRY_SPACING_SECONDS)
            agnes_video_id, error, was_content_policy = _submit_clip_raw(
                _build_prompt(sanitized if sanitized and sanitized != description else description),
                num_frames,
                anchor_image_url=None,
            )

        if was_content_policy:
            print(
                f"Shot {shot_index}: still content policy rejected - retrying once more "
                f"with the specific description AND camera move dropped entirely (true generic fallback)."
            )
            time.sleep(CONTENT_POLICY_RETRY_SPACING_SECONDS)
            generic_prompt = _build_prompt(
                "a cinematic documentary establishing shot of the scene", include_camera=False
            )
            agnes_video_id, error, was_content_policy = _submit_clip_raw(
                generic_prompt, num_frames, anchor_image_url=None
            )

        if was_content_policy:
            return None, f"CONTENT POLICY REJECTED even after sanitized, no-anchor, and true-generic-fallback retries — reword this shot's description: {description!r}"

    return agnes_video_id, error


def _extract_video_url(data):
    for key in ("video_url", "url", "output_url", "result_url"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        val = metadata.get("url")
        if isinstance(val, str) and val.startswith("http"):
            return val
    for val in data.values():
        if isinstance(val, str) and val.startswith("http") and val.endswith(".mp4"):
            return val
    return None


def _poll_clip(video_id):
    waited = 0
    last_data = None
    while waited < MAX_WAIT_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
        try:
            check = requests.get(
                AGNES_POLL_URL,
                params={"video_id": video_id, "model_name": "agnes-video-v2.0"},
                headers=HEADERS,
                timeout=30,
            )
        except requests.RequestException:
            continue
        if check.status_code != 200:
            continue
        data = check.json()
        last_data = data
        if data.get("status") == "completed":
            url = _extract_video_url(data)
            if url:
                return url, None
            return None, f"completed but no video URL found in response: {data}"
        if data.get("status") == "failed":
            return None, f"generation failed: {data.get('error')}"
    return None, f"timed out waiting for clip. Last poll response: {last_data}"


def _generate_shot_clip(video_id, description, shot_index, target_seconds, elapsed_seconds_before_shot):
    # ADDED (2026-08-23): FREEZE-FRAME FIX Phase 3 - see module docstring.
    # Shots that fit within a single Agnes call keep the exact previous
    # behavior. Shots that don't now chain multiple real segments instead
    # of generating one short clip that assemble.py would freeze-pad.
    raw_frames_needed = int(target_seconds * CLIP_FRAME_RATE)

    if raw_frames_needed <= MAX_FRAMES:
        frames = round_to_valid_frames(max(MIN_FRAMES, min(MAX_FRAMES, raw_frames_needed)))
        agnes_id, error = _submit_clip(
            description, shot_index, frames, elapsed_seconds_before_shot, anchor_image_url=None
        )
        if not agnes_id:
            return None, error
        return _poll_clip(agnes_id)

    print(
        f"Shot {shot_index}: target {target_seconds:.1f}s exceeds single-generation cap "
        f"(~{MAX_FRAMES / CLIP_FRAME_RATE:.1f}s) - chain-extending up to {MAX_CHAIN_SEGMENTS} segments."
    )

    segment_paths = []
    remaining = target_seconds
    anchor_url = None
    seg_index = 0
    last_error = None

    while remaining > 0.5 and seg_index < MAX_CHAIN_SEGMENTS:
        seg_raw_frames = int(remaining * CLIP_FRAME_RATE)
        seg_frames = round_to_valid_frames(max(MIN_FRAMES, min(MAX_FRAMES, seg_raw_frames)))

        agnes_id, error = _submit_clip(
            description, shot_index, seg_frames, elapsed_seconds_before_shot, anchor_image_url=anchor_url
        )
        if not agnes_id:
            last_error = error
            break

        seg_url, error = _poll_clip(agnes_id)
        if not seg_url:
            last_error = error
            break

        local_path = f"/tmp/_chain_{video_id}_shot{shot_index}_seg{seg_index}.mp4"
        if not _download_file(seg_url, local_path):
            last_error = f"failed to download chain segment {seg_index}"
            break

        segment_paths.append(local_path)
        remaining -= seg_frames / CLIP_FRAME_RATE
        seg_index += 1

        if remaining > 0.5 and seg_index < MAX_CHAIN_SEGMENTS:
            anchor_url = _extract_last_frame_url(seg_url, f"{video_id}_shot{shot_index}_seg{seg_index}")

    if not segment_paths:
        return None, last_error or "chain extension produced no segments"

    if len(segment_paths) == 1:
        stitched_path = segment_paths[0]
    else:
        stitched_path = f"/tmp/_chain_{video_id}_shot{shot_index}_stitched.mp4"
        if not _concat_segments(segment_paths, stitched_path):
            for p in segment_paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
            return None, "failed to concatenate chain segments"

    clip_url = _upload_clip(f"{video_id}_shot{shot_index:03d}", stitched_path)

    for p in segment_paths:
        try:
            os.remove(p)
        except OSError:
            pass
    if stitched_path not in segment_paths:
        try:
            os.remove(stitched_path)
        except OSError:
            pass

    if not clip_url:
        return None, "chain-extended clip generated but upload to backend failed"

    covered = target_seconds - max(remaining, 0.0)
    if remaining > 0.5:
        print(
            f"Shot {shot_index}: chain-extension covered {covered:.1f}s of {target_seconds:.1f}s "
            f"target after {seg_index} real segment(s) (cap reached) - assemble.py will still "
            f"freeze-pad the remaining {remaining:.1f}s."
        )
    else:
        print(
            f"Shot {shot_index}: chain-extension fully covered {target_seconds:.1f}s target with "
            f"{seg_index} real segment(s), no freeze-pad needed."
        )
    return clip_url, None


def _save_progress(video_id, clip_urls):
    try:
        patch_resp = requests.patch(
            f"{RAILWAY_URL}/api/v1/videos/{video_id}",
            json={"clip_urls": clip_urls},
            timeout=30,
        )
        patch_resp.raise_for_status()
        filled = len([u for u in clip_urls if u])
        print(f"Saved progress to Railway: {filled}/{len(clip_urls)} clips (position-preserved).")
    except requests.RequestException as e:
        print(f"WARNING: failed to save progress to Railway: {type(e).__name__}: {str(e)[:150]}")


def main():
    video_id = VIDEO_ID
    if not video_id:
        print("No VIDEO_ID provided — auto-selecting next video needing clips...")
        video_id = _find_next_video_needing_clips()
        if not video_id:
            print("No videos currently need clips. Exiting cleanly.")
            return
        print(f"Auto-selected video_id: {video_id}")

    print("Fetching video data from Railway...")
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos/{video_id}", timeout=90)
    resp.raise_for_status()
    video = resp.json()

    production_plan = video.get("production_plan")
    if not production_plan:
        print("ERROR: video has no production_plan")
        sys.exit(1)

    all_shots = _parse_shots(production_plan)
    if not all_shots:
        print("ERROR: no shots parsed from production_plan")
        sys.exit(1)

    total = len(all_shots)

    existing = video.get("clip_urls") or []
    clip_urls = [None] * total
    for i in range(min(len(existing), total)):
        clip_urls[i] = existing[i]

    already_done = [i for i, u in enumerate(clip_urls) if u]
    missing = [i for i, u in enumerate(clip_urls) if not u]

    print(f"Total shots: {total}. Already done: {len(already_done)}. Missing: {len(missing)}.")

    if not missing:
        print("All shots already have clips. Nothing to do.")
        return

    # CHANGED (2026-08-16): cross-shot chaining removed entirely - every
    # shot's FIRST segment still generates independently from its own text
    # description, no character reference image, no anchor carried over
    # from a previous shot. WITHIN-shot chain-extension (2026-08-23, see
    # module docstring) is separate and does not change this.
    print("Cross-shot chaining is disabled - each shot starts fresh from text only. "
          "Shots longer than the single-generation cap chain-extend internally (see below).")

    batch = missing[:BATCH_SIZE]
    print(f"This run will process {len(batch)} shot(s): {batch}")

    failure_reasons = []
    last_submit_time = 0.0

    # item #8: precompute true cumulative elapsed seconds at the start of
    # each shot in the video's full timeline (not just this batch), so
    # camera-move bucketing stays correct even when a run resumes partway
    # through a video across multiple workflow invocations. Done vs.
    # missing doesn't matter here - it's about story position, not
    # generation status.
    cumulative_by_index = [0.0] * total
    running = 0.0
    for i in range(total):
        cumulative_by_index[i] = running
        running += _shot_target_seconds(video, i, total)

    for index in batch:
        description = all_shots[index]
        target_seconds = _shot_target_seconds(video, index, total)

        elapsed = time.monotonic() - last_submit_time
        if elapsed < MIN_SECONDS_BETWEEN_SUBMITS and last_submit_time > 0:
            wait_for = MIN_SECONDS_BETWEEN_SUBMITS - elapsed
            print(f"Waiting {wait_for:.0f}s before next submission (rate limit)...")
            time.sleep(wait_for)

        last_submit_time = time.monotonic()
        print(f"Shot {index+1}/{total}: target {target_seconds:.1f}s")

        url, error = _generate_shot_clip(
            video_id, description, index, target_seconds, cumulative_by_index[index]
        )

        if url:
            clip_urls[index] = url
            print(f"Shot {index+1}/{total}: OK -> {url}")
        else:
            failure_reasons.append(f"shot {index}: {error}")
            print(f"Shot {index+1}/{total}: FAILED ({error})")
            if error and "RATE LIMITED" in error:
                print("Backing off 60s after a 429 before continuing this run...")
                time.sleep(60)

        _save_progress(video_id, clip_urls)
        good_so_far = len([u for u in clip_urls if u])
        print(f"Progress: {good_so_far}/{total} clips done overall.")

    generated_this_run = len([i for i in batch if clip_urls[i]])
    failed_this_run = len(batch) - generated_this_run
    print(f"BATCH DONE. This run generated: {generated_this_run}, failed: {failed_this_run}")
    if failure_reasons:
        print("Failure reasons:", failure_reasons)

    remaining = total - len([u for u in clip_urls if u])
    print(f"Remaining shots still needed: {remaining}")


if __name__ == "__main__":
    main()
