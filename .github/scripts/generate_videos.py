"""
Nova Command Center - Video Generation Agent

[... all prior docstring history unchanged through 2026-08-16 character-
reference fix ...]

UPDATED (2026-08-16, same session, Phase 1) - ported three prompt-only
fixes from Marius's video_generation.py after direct comparison:
1. MOTION_CONTINUITY_GUARD: added to stop non-purposeful movement flagged
   directly by Zia (people walking by default even when the scene doesn't
   call for it, reversing/snapping motion, pausing mid-action).
2. DISTINCT_INDIVIDUALS_GUARD: stops cloned faces/bodies across a crowd
   or background group.
3. QUALITY_GUARD rewritten from "shot on film, natural film grain" to
   Marius's 2026-08-15 "modern high-end digital cinema" phrasing - the
   grain/analog language was part of the quality gap vs Marius that Zia
   flagged.
No API cost, no schema change, no interaction with the content-policy
retry chain - safe as a standalone prompt-text change.
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
CLIP_HEIGHT = 768
CLIP_WIDTH = 1152
CLIP_FRAME_RATE = 24
MIN_FRAMES = 49    # ~2s floor, matches Marius
MAX_FRAMES = 169   # ~7s ceiling, matches Marius's MAX_CLIP_SECONDS
DEFAULT_SHOT_SECONDS = 5.0  # only used if shot_durations is unavailable for this video
MAX_WAIT_SECONDS = 240
POLL_INTERVAL_SECONDS = 10
MIN_SECONDS_BETWEEN_SUBMITS = 10  # FIX (2026-08-13): was 4 - too tight, let content-policy retry bursts trip real 429s
AGNES_IMAGE_MAX_RETRIES = 3
CONTENT_POLICY_RETRY_SPACING_SECONDS = 20  # FIX (2026-08-13): was 5 - too tight, see module docstring

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "20"))

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)
HEADERS = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}

CAMERA_MOVES = [
    "sweeping drone-style push-in",
    "fast tracking shot alongside the subject",
    "dramatic low-angle tilt up",
    "smooth rapid reveal shot",
    "slow dramatic zoom with parallax",
    "handheld tracking shot, urgent energy",
    "sweeping crane shot rising over the scene",
    "tight dynamic close-up with shallow depth of field",
]

LENS_STYLES = [
    "shot on 35mm anamorphic lens, shallow depth of field, subtle lens flare",
    "shot on vintage 50mm prime lens, soft natural bokeh, warm film tone",
    "wide-angle lens, deep focus, expansive epic framing",
    "telephoto compression, soft background blur, natural motion blur",
]

LIGHTING_DIRECTIVE = (
    "bright, clearly and evenly lit scene, strong daylight or warm well-lit "
    "interior lighting, high visibility, no heavy shadows, no underexposed or "
    "murky darkness"
)

ANACHRONISM_GUARD = (
    "historically accurate to this exact time period and setting, no modern technology, "
    "no cars, no drones, no modern clothing, no digital devices, no anachronistic objects of any kind, "
    "no laptops, no computers, no smartphones, no tablets, no screens or monitors of any kind, "
    "no modern furniture, no electrical wiring or outlets, no plastic objects"
)

# REWRITTEN (2026-08-16, Phase 1): was "shot on film, natural film grain,
# vivid saturated color..." - matched Marius pre-2026-08-15. Ported
# Marius's 2026-08-15 rewrite: modern digital-cinema look instead of
# analog film grain, which was part of the quality gap Zia flagged
# directly ("Marius's quality is much better").
QUALITY_GUARD = (
    "modern high-end digital cinema, crisp sharp clarity, professional color grading, "
    "shallow depth of field, cinematic lighting, vivid saturated color, no sepia tone, "
    "no heavy desaturation, no muted documentary color grading, no grainy vintage film look, "
    "no artificial CGI look, no flat synthetic AI look, no plastic skin"
)

# ADDED (2026-08-16, Phase 1): ported from Marius's video_generation.py.
# Directly addresses Zia's "why is everybody walking all the time, it is
# not required" feedback plus the broader "non-purposeful movement" note -
# stops the model defaulting to constant walking/motion and stops
# reversing/snapping/pause-mid-action artifacts.
MOTION_CONTINUITY_GUARD = (
    "movement in this shot is purposeful and matches what the scene actually calls for - "
    "the subject only walks, gestures, or moves if the action requires it, otherwise remains "
    "still or engaged in a static action (standing, sitting, working with hands); "
    "motion continues smoothly and continuously in the same direction and speed, "
    "no reversing, no snapping backward, no sudden stop-and-restart, no pausing mid-motion, "
    "no aimless or unmotivated walking"
)

# ADDED (2026-08-16, Phase 1): ported from Marius's video_generation.py.
# Stops cloned faces/bodies repeating across a crowd or background group.
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


def _parse_shots(production_plan):
    shots = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not SHOT_START.match(line):
            continue
        remainder = SHOT_START.sub("", line).strip()
        remainder = re.sub(r"^[\s:\-–\*]+", "", remainder)
        remainder = re.split(r"\*{0,2}Duration\*{0,2}\s*:", remainder, maxsplit=1, flags=re.IGNORECASE)[0]
        remainder = re.split(r"\bCamera\s*:", remainder, maxsplit=1, flags=re.IGNORECASE)[0]
        remainder = remainder.replace("**", "").replace("*", "").strip().rstrip(".").strip()
        if remainder:
            shots.append(remainder)
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


def _extract_last_frame_url(video_url_of_clip, out_tag):
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


def _submit_clip(description, shot_index, num_frames, anchor_image_url=None):
    camera_move = CAMERA_MOVES[shot_index % len(CAMERA_MOVES)]
    lens_style = LENS_STYLES[shot_index % len(LENS_STYLES)]
    # ADDED (2026-08-16, Phase 1): only apply the distinct-individuals guard
    # when the shot description actually implies multiple people, same
    # trigger pattern Marius uses (CROWD_OR_GROUP_KEYWORDS), so single-
    # character shots don't get an irrelevant guard phrase padded in.
    is_group_shot = any(kw in description.lower() for kw in CROWD_OR_GROUP_KEYWORDS)

    def _build_prompt(desc, include_camera=True):
        if not include_camera:
            parts = [
                LIGHTING_DIRECTIVE, QUALITY_GUARD, ANACHRONISM_GUARD, MOTION_CONTINUITY_GUARD,
            ]
            if is_group_shot:
                parts.append(DISTINCT_INDIVIDUALS_GUARD)
            parts += [
                desc, "shot by a Hollywood cinematographer, steady centered composition, "
                "documentary style, realistic motion, high detail",
            ]
            return ", ".join(p for p in parts if p)
        parts = [
            LIGHTING_DIRECTIVE, QUALITY_GUARD, ANACHRONISM_GUARD, MOTION_CONTINUITY_GUARD,
        ]
        if is_group_shot:
            parts.append(DISTINCT_INDIVIDUALS_GUARD)
        parts += [
            desc, f"shot by a Hollywood cinematographer, {camera_move}, {lens_style}",
            "high-energy fast-paced documentary style",
            "realistic motion, natural motion blur, high detail, engaging dynamic composition",
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

    anchor_image_url = video.get("character_reference_url")
    if not anchor_image_url and 0 not in missing and clip_urls:
        last_done_index = max(already_done) if already_done else None
        if last_done_index is not None and clip_urls[last_done_index]:
            print(f"Resuming mid-video - reconstructing continuity anchor from shot {last_done_index + 1}'s clip...")
            anchor_image_url = _extract_last_frame_url(clip_urls[last_done_index], f"{video_id}_resume")
    if not anchor_image_url:
        print("Generating character reference image for continuity anchoring...")
        opening_shot_description = all_shots[0] if all_shots else None
        anchor_image_url = generate_character_reference(video_id, video.get("title", ""), opening_shot_description)
    if anchor_image_url:
        print(f"Using continuity anchor: {anchor_image_url}")
    else:
        print("No continuity anchor available - shots will generate blind (text-to-video only) this run.")

    batch = missing[:BATCH_SIZE]
    print(f"This run will process {len(batch)} shot(s): {batch}")

    failure_reasons = []
    last_submit_time = 0.0

    for index in batch:
        description = all_shots[index]
        target_seconds = _shot_target_seconds(video, index, total)
        raw_frames = int(target_seconds * CLIP_FRAME_RATE)
        raw_frames = max(MIN_FRAMES, min(MAX_FRAMES, raw_frames))
        num_frames = round_to_valid_frames(raw_frames)
        num_frames = max(MIN_FRAMES, min(MAX_FRAMES, num_frames))

        elapsed = time.monotonic() - last_submit_time
        if elapsed < MIN_SECONDS_BETWEEN_SUBMITS and last_submit_time > 0:
            wait_for = MIN_SECONDS_BETWEEN_SUBMITS - elapsed
            print(f"Waiting {wait_for:.0f}s before next submission (rate limit)...")
            time.sleep(wait_for)

        last_submit_time = time.monotonic()
        print(f"Shot {index+1}/{total}: target {target_seconds:.1f}s ({num_frames} frames)")
        agnes_video_id, error = _submit_clip(description, index, num_frames, anchor_image_url=anchor_image_url)

        if not agnes_video_id:
            failure_reasons.append(f"shot {index}: {error}")
            print(f"Shot {index+1}/{total}: FAILED ({error})")
            if error and "RATE LIMITED" in error:
                print("Backing off 60s after a 429 before continuing this run...")
                time.sleep(60)
        else:
            url, error = _poll_clip(agnes_video_id)
            if url:
                clip_urls[index] = url
                print(f"Shot {index+1}/{total}: OK -> {url}")
                next_anchor = _extract_last_frame_url(url, f"{video_id}_shot{index:03d}")
                anchor_image_url = next_anchor or anchor_image_url
            else:
                failure_reasons.append(f"shot {index}: {error}")
                print(f"Shot {index+1}/{total}: FAILED ({error})")

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
