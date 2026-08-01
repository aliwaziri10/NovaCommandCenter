import asyncio
import os
import random
import re
import sys
import time

import requests
import edge_tts
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

RAILWAY_URL = os.environ["RAILWAY_URL"]
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()

VOICE_NAME = os.environ.get("VOICE", "en-US-GuyNeural")
BASE_RATE = -5  # percent, matches prior flat setting as the baseline

PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 2.0

WORK_DIR = "/tmp/nova_narration"
BACKEND_TIMEOUT = 120

LEADING_BRACKET_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")

SHOT_START = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)
DEFAULT_SHOT_DURATION = 3.0


def _get_with_wakeup(url, max_attempts=4, **kwargs):
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
        stripped = LEADING_BRACKET_TAG_RE.sub("", stripped).strip()
        if not stripped:
            continue
        clean_lines.append(stripped)
    return " ".join(clean_lines)


def _audio_path_is_live(audio_path):
    try:
        resp = requests.head(audio_path, timeout=15, allow_redirects=True)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"audio_path check failed for {audio_path} ({e}) - treating as dead.")
        return False


def _find_next_video_needing_narration():
    resp = _get_with_wakeup(f"{RAILWAY_URL}/api/v1/videos")
    resp.raise_for_status()
    videos = resp.json()

    candidates = []
    for v in videos:
        if not v.get("production_plan"):
            continue
        audio_path = v.get("audio_path")
        if not audio_path:
            candidates.append(v)
            continue
        if not _audio_path_is_live(audio_path):
            print(f"Video {v.get('id')} has audio_path set but the file is missing/dead - "
                  f"treating as needing re-narration: {audio_path}")
            candidates.append(v)

    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    return candidates[0]["id"]


def split_into_segments(narration_text):
    raw_segments = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    segments = [seg.strip() for seg in raw_segments if seg.strip()]
    return segments if segments else [narration_text.strip()]


# --- Prosody variation (added 2026-08-02) ---
# A single flat rate for every sentence is one of the most obvious "AI voice"
# tells - real human narrators speed up for punchy/tense lines, slow down for
# weighty ones, and lift pitch on questions. This picks a rate/pitch per
# sentence based on its shape (question, short/punchy, long) plus a small
# bounded random jitter so back-to-back sentences of the same type don't
# sound identically robotic either. Bounds are kept tight so it reads as
# natural variation, not erratic or distracting.
def _prosody_for_sentence(text, index):
    rng = random.Random(index)  # deterministic per-sentence, still varies run to run via index
    word_count = len(text.split())
    is_question = text.rstrip().endswith("?")
    is_exclamation = text.rstrip().endswith("!")

    rate = BASE_RATE
    pitch = 0

    if is_question:
        pitch += rng.randint(2, 5)
        rate += rng.randint(-2, 1)
    elif is_exclamation or word_count <= 7:
        rate += rng.randint(2, 6)
        pitch += rng.randint(1, 3)
    elif word_count >= 25:
        rate += rng.randint(-8, -4)
        pitch += rng.randint(-2, 0)
    else:
        rate += rng.randint(-3, 2)
        pitch += rng.randint(-1, 2)

    rate = max(-20, min(15, rate))
    pitch = max(-6, min(8, pitch))
    rate_str = f"{'+' if rate >= 0 else ''}{rate}%"
    pitch_str = f"{'+' if pitch >= 0 else ''}{pitch}Hz"
    return rate_str, pitch_str


async def _synthesize_sentence(text, voice, rate, pitch, out_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


def synthesize_sentence(text, voice, rate, pitch, tmp_path):
    asyncio.run(_synthesize_sentence(text, voice, rate, pitch, tmp_path))
    return AudioSegment.from_file(tmp_path)


def synthesize_with_pauses(narration_text, voice):
    segments = split_into_segments(narration_text)
    print(f"Narration split into {len(segments)} sentence(s) for pause insertion and prosody variation.")

    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(segments):
        rate, pitch = _prosody_for_sentence(segment, i)
        clip = synthesize_sentence(segment, voice, rate, pitch, os.path.join(WORK_DIR, f"sent_{i}.mp3"))
        combined += clip
        if i < len(segments) - 1:
            pause_len = PAUSE_SECONDS_MIN if i % 2 == 0 else PAUSE_SECONDS_MAX
            combined += AudioSegment.silent(duration=int(pause_len * 1000))

    return combined, len(combined) / 1000.0


def _parse_shots_with_durations(production_plan):
    durations = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not SHOT_START.match(line):
            continue
        match = DURATION_PATTERN.search(line)
        durations.append(float(match.group(1)) if match else DEFAULT_SHOT_DURATION)
    return durations


def _scale_shot_durations(planned_durations, real_total_seconds):
    if not planned_durations:
        return []
    planned_total = sum(planned_durations)
    if planned_total <= 0:
        even_share = real_total_seconds / len(planned_durations)
        return [even_share] * len(planned_durations)
    scale = real_total_seconds / planned_total
    return [d * scale for d in planned_durations]


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

    print(f"Generating speech with Edge TTS voice: {VOICE_NAME} (sentence-level, prosody-varied, real pauses)")
    combined_audio, real_total_seconds = synthesize_with_pauses(narration_text, VOICE_NAME)
    combined_audio = pydub_normalize(combined_audio)
    print(f"Real measured narration length: {real_total_seconds:.1f}s")

    shot_durations = None
    production_plan = video.get("production_plan")
    if production_plan:
        planned_durations = _parse_shots_with_durations(production_plan)
        if planned_durations:
            shot_durations = _scale_shot_durations(planned_durations, real_total_seconds)
            print(f"Computed {len(shot_durations)} real per-shot durations "
                  f"(scaled from planned, summing to {sum(shot_durations):.1f}s).")
        else:
            print("No shots parsed from production_plan yet - skipping shot_durations for now.")
    else:
        print("No production_plan yet on this video - skipping shot_durations for now.")

    wav_path = os.path.join(WORK_DIR, "narration.wav")
    combined_audio.export(wav_path, format="wav")

    print("Converting WAV to MP3")
    import subprocess
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

    if shot_durations is not None:
        print("Saving real shot_durations to backend")
        patch_resp = requests.patch(
            f"{RAILWAY_URL}/api/v1/videos/{video_id}",
            json={"shot_durations": shot_durations},
            timeout=30,
        )
        patch_resp.raise_for_status()
        print("shot_durations saved.")


if __name__ == "__main__":
    main()
