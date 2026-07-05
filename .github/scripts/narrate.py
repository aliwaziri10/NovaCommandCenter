import os
import sys
import subprocess
import numpy as np
import requests
import soundfile as sf
from kokoro import KPipeline

RAILWAY_URL = os.environ["RAILWAY_URL"]
VIDEO_ID = os.environ["VIDEO_ID"]
VOICE = os.environ.get("VOICE", "am_adam")

WORK_DIR = "/tmp/nova_narration"


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


def main():
    os.makedirs(WORK_DIR, exist_ok=True)

    print("Fetching video data from Railway...")
    video_resp = requests.get(f"{RAILWAY_URL}/api/v1/videos/{VIDEO_ID}", timeout=30)
    video_resp.raise_for_status()
    video = video_resp.json()

    script_id = video.get("script_id")
    if not script_id:
        print("ERROR: video has no script_id")
        sys.exit(1)

    print("Fetching script data from Railway...")
    script_resp = requests.get(f"{RAILWAY_URL}/api/v1/scripts/{script_id}", timeout=30)
    script_resp.raise_for_status()
    script = script_resp.json()

    raw_content = script.get("content")
    if not raw_content:
        print("ERROR: script has no content")
        sys.exit(1)

    narration_text = _clean_narration_text(raw_content)
    print(f"Narration text length: {len(narration_text)} characters")

    print(f"Generating speech with Kokoro voice '{VOICE}'...")
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

    print("Converting
