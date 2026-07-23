import os
import re
import sys
import time
from urllib.parse import quote

import requests

RAILWAY_URL = os.environ["RAILWAY_URL"]
ASSEMBLY_SECRET = os.environ["ASSEMBLY_SECRET"]
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()

IMAGE_MODEL = "flux"
IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080

RETRYABLE_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 4

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)
HEADERS = {"X-Assembly-Secret": ASSEMBLY_SECRET}


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


def _find_next_video_needing_images():
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos", timeout=30)
    resp.raise_for_status()
    videos = resp.json()

    candidates = []
    for v in videos:
        if v.get("status") == "assembled":
            continue
        if not v.get("audio_path"):
            continue
        production_plan = v.get("production_plan")
        if not production_plan:
            continue
        shots = _parse_shots(production_plan)
        if not shots:
            continue
        # Count FILLED slots, not raw list length - asset_urls is now a
        # fixed-length, position-aligned list (null = not generated yet),
        # same convention as clip_urls. len() alone would look "done" even
        # with gaps once the list is padded to full length.
        existing_urls = v.get("asset_urls") or []
        filled = sum(1 for u in existing_urls if u)
        if filled < len(shots):
            candidates.append(v)

    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    return candidates[0]["id"]


def _fetch_image_with_retry(url):
    """GETs the Pollinations URL to verify it renders, retrying transient
    errors (429/500/502/503/504) with backoff instead of failing permanently
    on the first blip - matching the retry pattern already used for every
    Agnes call in this codebase."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=60)
        except requests.RequestException as e:
            last_error = f"{type(e).__name__}: {str(e)[:100]}"
            wait = 15 * (attempt + 1)
            print(f"Request error (attempt {attempt + 1}/{MAX_RETRIES}): {last_error}. Retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return True, None

        if resp.status_code in RETRYABLE_CODES:
            last_error = f"HTTP {resp.status_code}"
            wait = 15 * (attempt + 1)
            print(f"Transient error (attempt {attempt + 1}/{MAX_RETRIES}): {last_error}. Retrying in {wait}s...")
            time.sleep(wait)
            continue

        return False, f"HTTP {resp.status_code}"

    return False, f"still failing after {MAX_RETRIES} attempts: {last_error}"


def _save_progress(video_id, asset_urls):
    # Save the list AS-IS, preserving null placeholders and shot position -
    # same fix already applied to clip_urls. Compacting this (dropping
    # failed slots) shifts every image after a failure onto the wrong shot.
    patch_resp = requests.patch(
        f"{RAILWAY_URL}/api/v1/videos/{video_id}",
        json={"asset_urls": asset_urls},
        timeout=30,
    )
    patch_resp.raise_for_status()
    filled = len([u for u in asset_urls if u])
    print(f"Saved progress: {filled}/{len(asset_urls)} images (position-preserved).")


def main():
    video_id = VIDEO_ID
    if not video_id:
        print("No VIDEO_ID provided — auto-selecting next video needing images...")
        video_id = _find_next_video_needing_images()
        if not video_id:
            print("No videos currently need images. Exiting cleanly.")
            return
        print(f"Auto-selected video_id: {video_id}")

    print("Fetching video data from Railway...")
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos/{video_id}", timeout=30)
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

    existing = video.get("asset_urls") or []
    asset_urls = [None] * total
    for i in range(min(len(existing), total)):
        asset_urls[i] = existing[i]

    already_done = [i for i, u in enumerate(asset_urls) if u]
    missing = [i for i, u in enumerate(asset_urls) if not u]

    print(f"Total shots: {total}. Already done: {len(already_done)}. Missing: {len(missing)}.")

    if not missing:
        print("All shots already have images. Nothing to do.")
        return

    failure_reasons = []

    for i in missing:
        description = all_shots[i]
        prompt = (
            f"{description}, cinematic documentary photography, "
            f"hyper-realistic, ultra detailed, natural lighting, 8k, film grain, "
            f"professional color grading, widescreen composition"
        )
        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            f"?model={IMAGE_MODEL}&width={IMAGE_WIDTH}&height={IMAGE_HEIGHT}"
        )

        ok, error = _fetch_image_with_retry(url)
        if ok:
            asset_urls[i] = url
            print(f"Shot {i+1}/{total}: OK")
        else:
            failure_reasons.append(f"shot {i}: {error}")
            print(f"Shot {i+1}/{total}: FAILED ({error})")

        time.sleep(2)

        if (i + 1) % 10 == 0 or (i + 1) == total:
            _save_progress(video_id, asset_urls)

    _save_progress(video_id, asset_urls)

    generated = len([i for i in missing if asset_urls[i]])
    failed = len(missing) - generated
    print(f"DONE. Generated: {generated}, Failed: {failed}")
    if failure_reasons:
        print("Failure reasons:", failure_reasons)


if __name__ == "__main__":
    main()
