import os
import sys
import subprocess
import time
import numpy as np
import requests
import soundfile as sf
from kokoro import KPipeline

RAILWAY_URL = os.environ["RAILWAY_URL"]  # name is legacy - this actually points to Render now
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()
VOICE = os.environ.get("VOICE", "am_adam")

WORK_DIR = "/tmp/nova_narration"
BACKEND_TIMEOUT = 120  # Render cold starts can run past 30s


def _get_with_wakeup(url, max_attempts=4, **kwargs):
    """
    GETs a URL, retrying with backoff if the Render free-tier backend
    is asleep and slow to wake up (read timeout / connection error).
    """
    backoff_seconds = [10, 20, 40, 60]
    kwargs.setdefault("timeout", BACKEND_TIMEOUT)

    for attempt in range(1, max_attempts + 1):
        try:
            return requests.get(url, **kwargs)
        except requests.exceptions.ReadTimeout:
            print(f"Backend not awake yet (attempt {attempt}/{max_attempts}): read timeout")
        except requests.exceptions.ConnectionError as e:
            print(f"Backend not reachable yet (attempt {attempt}/{max_attempts}): {e}")

        if attempt < max_attempts:
            wait = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
            print(f"Waiting {wait}s before retry...")
            time.sleep(wait)

    raise RuntimeError(f"Backend at {url} did not respond after {max_attempts} attempts.")


def _clean_narration_text(raw_content):
    clean_lines = []
    for line in raw_content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if stripped.upper().startswith("NARRATOR"):
            continue
        clean_lines.append(stripped)
    return " ".join(clean_lines)


def _find_next_video_needing_narration():
    resp = _get_with_wakeup(f"{RAILWAY_URL}/api/v1/videos")
    resp.raise_for_status()
    videos = resp.json()
    candidates = [
        v for v in videos
        if v.get("production_plan") and not v.get("audio_path")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    return candidates[0]["id"]


def main():
    os.makedirs(WORK_DIR, exist_ok=True)

    video_id = VIDEO_ID
    if not video_id:
        print("No VIDEO_ID provided — auto-selecting next video needing narration...")
        video_id = _find_next_video_needing_narration()
        if not video_id:
            print("No videos currently need narration. Exiting cleanly.")
            return
        print(f"Auto-selected video_id: {video_id}")

    print("Fetching video data from backend")
    video_resp = _get_with_wakeup(f"{RAILWAY_URL}/api/v1/videos/{video_id}")
    video_resp.raise_for_status()
    video = video_resp.json()

    script_id = video.get("script_id")
    if not script_id:
        print("ERROR: video has no script_id")
        sys.exit(1)

    print("Fetching script data from backend")
    script_resp = _get_with_wakeup(f"{RAILWAY_URL}/api/v1/scripts/{script_id}")
    script_resp.raise_for_status()
    script = script_resp.json()

    raw_content = script.get("content")
    if not raw_content:
        print("ERROR: script has no content")
        sys.exit(1)

    narration_text = _clean_narration_text(raw_content)
    print("Narration text length: " + str(len(narration_text)) + " characters")

    print("Generating speech with Kokoro voice: " + VOICE)
    pipeline = KPipeline(lang_code="a")
    all_audio = []
    for graphemes, phonemes, audio in pipeline(narration_text, voice=VOICE, speed=1.0):
        all_audio.append(audio)

    if not all_audio:
        print("ERROR: Kokoro produced no audio")
        sys.exit(1)

    combined = np.concatenate(all_audio)
    wav_path = os.path.join(WORK_DIR, "narration.wav")
    sf.write(wav_path, combined, 24000)

    print("Converting WAV to MP3")
    mp3_path = os.path.join(WORK_DIR, "narration.mp3")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-qscale:a", "2", mp3_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print("ffmpeg error: " + result.stdout.decode(errors="ignore"))
        sys.exit(1)

    print("Uploading narration to backend")
    with open(mp3_path, "rb") as f:
        upload_resp = requests.post(
            f"{RAILWAY_URL}/api/v1/upload/narration/{video_id}",
            files={"file": ("narration.mp3", f, "audio/mpeg")},
            timeout=120,
        )
    upload_resp.raise_for_status()
    print("SUCCESS")
    print(upload_resp.json())


if __name__ == "__main__":
    main()
