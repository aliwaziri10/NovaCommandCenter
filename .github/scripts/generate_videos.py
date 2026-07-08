import os
import re
import sys
import time

import requests

RAILWAY_URL = os.environ["RAILWAY_URL"]
VIDEO_ID = os.environ["VIDEO_ID"]
AGNES_API_KEY = os.environ["AGNES_API_KEY"]

AGNES_BASE = "https://apihub.agnes-ai.com/v1/videos"
CLIP_HEIGHT = 768
CLIP_WIDTH = 1152
CLIP_NUM_FRAMES = 121  # ~5 seconds at 24fps, must be 8*n+1
CLIP_FRAME_RATE = 24
MAX_WAIT_SECONDS = 240
POLL_INTERVAL_SECONDS = 10
MIN_SECONDS_BETWEEN_SUBMITS = 65  # Agnes allows 1 request per 60s — 65s gives safety margin

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "3"))

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)
HEADERS = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}


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


def _submit_clip(description):
    prompt = f"{description}, cinematic documentary style, realistic motion, high detail"
    body = {
        "model": "agnes-video-v2.0",
        "prompt": prompt,
        "height": CLIP_HEIGHT,
        "width": CLIP_WIDTH,
        "num_frames": CLIP_NUM_FRAMES,
        "frame_rate": CLIP_FRAME_RATE,
    }
    try:
        submit = requests.post(AGNES_BASE, headers=HEADERS, json=body, timeout=60)
    except requests.RequestException as e:
        return None, f"submit request error: {type(e).__name__}: {str(e)[:150]}"
    if submit.status_code != 200:
        return None, f"submit failed: HTTP {submit.status_code}: {submit.text[:200]}"
    task_id = submit.json().get("task_id")
    if not task_id:
        return None, "no task_id returned"
    return task_id, None


def _poll_clip(task_id):
    waited = 0
    while waited < MAX_WAIT_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
        try:
            check = requests.get(f"{AGNES_BASE}/{task_id}", headers=HEADERS, timeout=30)
        except requests.RequestException:
            continue
        if check.status_code != 200:
            continue
        data = check.json()
        if data.get("status") == "completed":
            return data.get("url"), None
        if data.get("status") == "failed":
            return None, f"generation failed: {data.get('error')}"
    return None, "timed out waiting for clip"


def _save_progress(clip_urls):
    good_so_far = [u for u in clip_urls if u]
    try:
        patch_resp = requests.patch(
            f"{RAILWAY_URL}/api/v1/videos/{VIDEO_ID}",
            json={"clip_urls": good_so_far},
            timeout=30,
        )
        patch_resp.raise_for_status()
        print(f"Saved progress to Railway: {len(good_so_far)} clips.")
    except requests.RequestException as e:
        print(f"WARNING: failed to save progress to Railway: {type(e).__name__}: {str(e)[:150]}")


def main():
    print("Fetching video data from Railway...")
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos/{VIDEO_ID}", timeout=30)
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

    batch = missing[:BATCH_SIZE]
    print(f"This run will process {len(batch)} shot(s): {batch}")

    failure_reasons = []
    last_submit_time = 0.0

    for index in batch:
        description = all_shots[index]

        elapsed = time.monotonic() - last_submit_time
        if elapsed < MIN_SECONDS_BETWEEN_SUBMITS and last_submit_time > 0:
            wait_for = MIN_SECONDS_BETWEEN_SUBMITS - elapsed
            print(f"Waiting {wait_for:.0f}s before next submission (rate limit)...")
            time.sleep(wait_for)

        last_submit_time = time.monotonic()
        task_id, error = _submit_clip(description)

        if not task_id:
            failure_reasons.append(f"shot {index}: {error}")
            print(f"Shot {index+1}/{total}: FAILED ({error})")
        else:
            url, error = _poll_clip(task_id)
            if url:
                clip_urls[index] = url
                print(f"Shot {index+1}/{total}: OK -> {url}")
            else:
                failure_reasons.append(f"shot {index}: {error}")
                print(f"Shot {index+1}/{total}: FAILED ({error})")

        _save_progress(clip_urls)
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
