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
        existing = len(v.get("asset_urls") or [])
        if existing < len(shots):
            candidates.append(v)

    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    return candidates[0]["id"]


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

    print(f"Parsed {len(all_shots)} shots. Generating images one at a time...")

    new_urls = []
    failure_reasons = []

    for i, description in enumerate(all_shots):
        prompt = (
            f"{description}, cinematic documentary photography, "
            f"hyper-realistic, ultra detailed, dramatic lighting, 8k, film grain, "
            f"professional color grading, widescreen composition"
        )
        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            f"?model={IMAGE_MODEL}&width={IMAGE_WIDTH}&height={IMAGE_HEIGHT}"
        )
        try:
            check = requests.get(url, timeout=60)
            if check.status_code == 200:
                new_urls.append(url)
                print(f"Shot {i+1}/{len(all_shots)}: OK")
            else:
                new_urls.append(None)
                failure_reasons.append(f"shot {i}: HTTP {check.status_code}")
                print(f"Shot {i+1}/{len(all_shots)}: FAILED (HTTP {check.status_code})")
        except requests.RequestException as e:
            new_urls.append(None)
            failure_reasons.append(f"shot {i}: {type(e).__name__}: {str(e)[:100]}")
            print(f"Shot {i+1}/{len(all_shots)}: FAILED ({type(e).__name__})")

        time.sleep(2)

        if (i + 1) % 10 == 0 or (i + 1) == len(all_shots):
            good_so_far = [u for u in new_urls if u]
            print(f"Saving progress: {len(good_so_far)} images so far...")
            patch_resp = requests.patch(
                f"{RAILWAY_URL}/api/v1/videos/{video_id}",
                json={"asset_urls": good_so_far},
                timeout=30,
            )
            patch_resp.raise_for_status()

    generated = len([u for u in new_urls if u])
    failed = len([u for u in new_urls if not u])
    print(f"DONE. Generated: {generated}, Failed: {failed}")
    if failure_reasons:
        print("Failure reasons:", failure_reasons)


if __name__ == "__main__":
    main()
