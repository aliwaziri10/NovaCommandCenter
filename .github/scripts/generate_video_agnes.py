import os
import re
import sys
import time
import subprocess
import requests

import imageio_ffmpeg

RAILWAY_URL = os.environ["RAILWAY_URL"]
ASSEMBLY_SECRET = os.environ["ASSEMBLY_SECRET"]
AGNES_API_KEY = os.environ["AGNES_API_KEY"]
VIDEO_ID = os.environ["VIDEO_ID"]

AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
FRAME_RATE = 24
DEFAULT_SHOT_DURATION = 4.0
CROSSFADE = 0.5
POLL_INTERVAL_SECONDS = 8
POLL_TIMEOUT_SECONDS = 240
REQUEST_GAP_SECONDS = 4  # stay under Agnes free-tier 20 RPM

WORK_DIR = "/tmp/nova_agnes_video"
FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SCENE_START = re.compile(r"^\*\*Scene\s*[\d.]+.*?[\u2013\-]\s*(\d+)\s*s\*\*", re.IGNORECASE)
SHOT_LINE = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**\s*:\s*(.*)", re.IGNORECASE)

AGNES_HEADERS = {
    "Authorization": f"Bearer {AGNES_API_KEY}",
    "Content-Type": "application/json",
}
RAILWAY_HEADERS = {"X-Assembly-Secret": ASSEMBLY_SECRET}


def _parse_shots(production_plan):
    """Returns a list of (description, duration_seconds) tuples, splitting
    each scene's total duration evenly across its listed shots."""
    shots = []
    current_scene_seconds = None
    current_scene_shots = []

    def _flush():
        if not current_scene_shots:
            return
        total = current_scene_seconds if current_scene_seconds else DEFAULT_SHOT_DURATION * len(current_scene_shots)
        per_shot = total / len(current_scene_shots)
        for desc in current_scene_shots:
            shots.append((desc, per_shot))

    for raw_line in production_plan.splitlines():
        line = raw_line.strip()
        scene_match = SCENE_START.match(line)
        if scene_match:
            _flush()
            current_scene_seconds = float(scene_match.group(1))
            current_scene_shots = []
            continue
        shot_match = SHOT_LINE.match(line)
        if shot_match:
            desc = shot_match.group(1).replace("**", "").strip().rstrip(".").strip()
            if desc:
                current_scene_shots.append(desc)

    _flush()
    return shots


def _submit_agnes_video(prompt, target_duration):
    num_frames = max(25, min(int(target_duration * FRAME_RATE), 121))
    payload = {
        "model": "agnes-video-v2.0",
        "prompt": f"{prompt}, cinematic documentary footage, realistic motion, dramatic lighting",
        "height": 768,
        "width": 1152,
        "num_frames": num_frames,
        "frame_rate": FRAME_RATE,
    }
    resp = requests.post(f"{AGNES_BASE_URL}/videos", headers=AGNES_HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("video_id") or data.get("id")


def _poll_agnes_video(video_id):
    waited = 0
    while waited < POLL_TIMEOUT_SECONDS:
        resp = requests.get(f"{AGNES_BASE_URL}/videos/{video_id}", headers=AGNES_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status == "completed":
            return data.get("video_url")
        if status == "failed":
            return None
        time.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS
    return None


def _download_file(url, dest_path):
    resp = requests.get(url, timeout=120)
    if resp.status_code == 200 and len(resp.content) > 0:
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return True
    return False


def _run_ffmpeg(args):
    full_args = [FFMPEG_BINARY, "-y"] + args
    result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        error_text = result.stdout.decode(errors="ignore")[-2000:]
        raise RuntimeError("ffmpeg failed: " + error_text)


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    clips_dir = os.path.join(WORK_DIR, "clips")
    os.makedirs(clips_dir, exist_ok=True)

    print("Fetching video data from Railway...")
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos/{VIDEO_ID}", timeout=30)
    resp.raise_for_status()
    video = resp.json()

    production_plan = video.get("production_plan")
    if not production_plan:
        print("ERROR: video has no production_plan")
        sys.exit(1)

    shots = _parse_shots(production_plan)
    if not shots:
        print("ERROR: no shots parsed from production_plan")
        sys.exit(1)
    print(f"Parsed {len(shots)} shots")

    print("Downloading narration audio from Railway...")
    audio_path = os.path.join(WORK_DIR, "narration.mp3")
    audio_resp = requests.get(
        f"{RAILWAY_URL}/api/v1/download/narration/{VIDEO_ID}",
        headers=RAILWAY_HEADERS,
        timeout=60,
    )
    audio_resp.raise_for_status()
    with open(audio_path, "wb") as f:
        f.write(audio_resp.content)

    clip_paths = []
    failures = []

    for i, (description, duration) in enumerate(shots):
        print(f"Shot {i}: submitting to Agnes ({duration:.1f}s target)...")
        try:
            video_task_id = _submit_agnes_video(description, duration)
            if not video_task_id:
                failures.append(f"shot {i}: no video_id returned")
                continue
            video_url = _poll_agnes_video(video_task_id)
            if not video_url:
                failures.append(f"shot {i}: generation failed or timed out")
                continue
            clip_path = os.path.join(clips_dir, "shot_%03d.mp4" % i)
            ok = _download_file(video_url, clip_path)
            if not ok:
                failures.append(f"shot {i}: download failed")
                continue
            clip_paths.append(clip_path)
            print(f"Shot {i}: done")
        except Exception as e:
            failures.append(f"shot {i}: {type(e).__name__}: {str(e)[:150]}")
        time.sleep(REQUEST_GAP_SECONDS)

    if not clip_paths:
        print("ERROR: all shots failed: " + str(failures))
        sys.exit(1)

    concat_list_path = os.path.join(WORK_DIR, "concat_list.txt")
    with open(concat_list_path, "w") as f:
        for p in clip_paths:
            safe_p = p.replace("'", "'\\''")
            f.write("file '" + safe_p + "'\n")

    silent_path = os.path.join(WORK_DIR, "silent_final.mp4")
    final_path = os.path.join(WORK_DIR, "final.mp4")

    print("Concatenating shot clips...")
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", silent_path])

    print("Merging narration audio...")
    _run_ffmpeg([
        "-i", silent_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        final_path,
    ])

    print("Uploading finished video back to Railway...")
    with open(final_path, "rb") as f:
        upload_resp = requests.post(
            f"{RAILWAY_URL}/api/v1/upload/video/{VIDEO_ID}",
            headers=RAILWAY_HEADERS,
            files={"file": ("final.mp4", f, "video/mp4")},
            timeout=300,
        )
    upload_resp.raise_for_status()

    print("SUCCESS:", upload_resp.json())
    if failures:
        print("Note: some shots failed:", failures)


if __name__ == "__main__":
    main()
