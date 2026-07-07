import os
import re
import sys
import time
import concurrent.futures

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
BATCH_SIZE = 5

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


def _generate_one(index, description):
    task_id, error = _submit_clip(description)
    if not task_id:
        return index, None, error
    url, error = _poll_clip(task_id)
    return index, url, error


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

    print(f"Parsed {len(all_shots)} shots. Generating video clips in batches of {BATCH_SIZE}...")

    clip_urls = [None] * len(all_shots)
    failure_reasons = []

    for batch_start in range(0, len(all_shots), BATCH_SIZE):
        batch_indices = list(range(batch_start, min(batch_start + BATCH_SIZE, len(all_shots))))
        print(f"Starting batch: shots {batch_indices}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            futures = [executor.submit(_generate_one, i, all_shots[i]) for i in batch_indices]
            for future in concurrent.futures.as_completed(futures):
                index, url, error = future.result()
                if url:
                    clip_urls[index] = url
                    print(f"Shot {index+1}/{len(all_shots)}: OK -> {url}")
                else:
                    failure_reasons.append(f"shot {index}: {error}")
                    print(f"Shot {index+1}/{len(all_shots)}: FAILED ({error})")

        good_so_far = [u for u in clip_urls if u]
        print(f"Progress checkpoint after batch: {len(good_so_far)}/{len(all_shots)} clips done so far.")

    generated = len([u for u in clip_urls if u])
    failed = len([u for u in clip_urls if not u])
    print(f"DONE. Generated: {generated}, Failed: {failed}")
    print("FINAL_CLIP_URLS_IN_ORDER:", clip_urls)
    if failure_reasons:
        print("Failure reasons:", failure_reasons)


if __name__ == "__main__":
    main()
