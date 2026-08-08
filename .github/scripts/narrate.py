import os
import re
import sys
import time

import requests
import torchaudio
from chatterbox.tts import ChatterboxTTS
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

RAILWAY_URL = os.environ["RAILWAY_URL"]
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()

# CHATTERBOX (ported from Marius, 2026-08-04): replaces Edge TTS. Runs on a
# GitHub-hosted runner (this workflow), same as Marius - plenty of RAM,
# no Render in-process risk. Chatterbox has no rate/pitch param, so the
# per-sentence prosody-variation trick used under Edge TTS is dropped;
# Chatterbox's own prosody is already more natural than Edge TTS's flat
# delivery was.
SLOWDOWN_FACTOR = "0.95"

PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 2.0

WORK_DIR = "/tmp/nova_narration"
BACKEND_TIMEOUT = 120

LEADING_BRACKET_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")

SHOT_START = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)
DEFAULT_SHOT_DURATION = 3.0

# GUARD (2026-08-04): this is the actual live pipeline path (triggered by the
# Supervisor Agent's automated 20-minute cycle) - narration_agent.py's
# equivalent guard only protects the separate manual/admin dashboard path,
# NOT this one. Without this, "Hidden Code"-style script corruption (a
# Pollinations error page saved as script content) can still reach TTS here
# even after script_writing_agent.py's 2026-08-03 fix, for any script row
# that predates that fix or reaches this script through any future path.
_CODE_LIKE_MARKERS = (
    "<html", "<!doctype", "<div", "<span", "<body", "<script",
    "```", "function(", "function (", "=>", "SELECT *", "import ",
    "def ", "class ", "{\"", "[{", "</",
)


def _looks_like_code_or_markup(text):
    lowered = text.lower()
    hits = sum(1 for marker in _CODE_LIKE_MARKERS if marker.lower() in lowered)
    if hits >= 2:
        return True
    symbol_count = sum(text.count(ch) for ch in "{}<>[]")
    if symbol_count > 5 and (symbol_count / max(len(text), 1)) > 0.01:
        return True
    return False


_tts_model = None


def get_tts_model():
    global _tts_model
    if _tts_model is None:
        _tts_model = ChatterboxTTS.from_pretrained(device="cpu")
    return _tts_model


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


def synthesize_sentence(text, tts, tmp_path):
    wav = tts.generate(text)
    torchaudio.save(tmp_path, wav, tts.sr)
    clip = AudioSegment.from_file(tmp_path)
    # DIAGNOSTIC (2026-08-09): added after Chatterbox's first live run produced
    # ~4s of audio for a ~555s-planned script - no exception was raised, so
    # there was no way to tell which sentence(s) actually failed to synthesize.
    # Logs each segment's real length so the next failure points at the exact
    # sentence(s) that came out wrong, instead of just the aggregate total.
    print(f"  segment ({len(text)} chars): {len(clip) / 1000.0:.2f}s audio -> {text[:60]!r}")
    return clip


def synthesize_with_pauses(narration_text, tts):
    segments = split_into_segments(narration_text)
    print(f"Narration split into {len(segments)} sentence(s) for pause insertion.")

    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(segments):
        clip = synthesize_sentence(segment, tts, os.path.join(WORK_DIR, f"sent_{i}.wav"))
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


# GUARD (2026-08-09): Chatterbox's first live production run measured
# real_total_seconds at ~4.1s for a script whose planned shots summed to
# ~555s (a ~130x shortfall) - every sentence apparently synthesized to
# near-nothing, but nothing raised an exception, so the corrupted length
# silently propagated into shot_durations and wrecked assemble.py's
# per-shot timing (each shot rendered at ~1/130th its real length,
# producing a near-empty final video that then crashed the ffmpeg merge
# step for an unrelated-looking reason). Refuse to trust a narration
# length this implausible - fail loudly here instead of quietly
# corrupting shot_durations for assemble.py to consume later.
MIN_PLAUSIBLE_RATIO = 0.15
MIN_SECONDS_PER_SEGMENT = 0.5


def _check_narration_length_plausible(real_total_seconds, planned_total_seconds, num_segments):
    if planned_total_seconds <= 0:
        return
    ratio = real_total_seconds / planned_total_seconds
    if ratio < MIN_PLAUSIBLE_RATIO or real_total_seconds < num_segments * MIN_SECONDS_PER_SEGMENT:
        raise RuntimeError(
            f"Narration length implausible: measured {real_total_seconds:.1f}s of audio "
            f"for a script whose planned shots sum to {planned_total_seconds:.1f}s "
            f"(ratio {ratio:.3f}, {num_segments} sentence segments). This almost certainly "
            f"means Chatterbox TTS produced near-empty audio for some/all segments - check "
            f"the per-segment lengths logged above for the exact sentence(s) that failed. "
            f"Refusing to upload this narration or save shot_durations."
        )


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

    if _looks_like_code_or_markup(raw_content):
        print(f"ERROR: script {script_id} looks like code/markup, not narration text - "
              f"refusing to narrate it. This script needs to be regenerated "
              f"(delete this Script row and re-run script_writing), not narrated as-is.")
        sys.exit(1)

    narration_text = _clean_narration_text(raw_content)
    print("Narration text length: " + str(len(narration_text)) + " characters")

    if _looks_like_code_or_markup(narration_text):
        print(f"ERROR: script {script_id} looks like code/markup after cleaning - refusing to narrate it.")
        sys.exit(1)

    print("Generating speech with Chatterbox TTS (sentence-level, real pauses)")
    tts = get_tts_model()
    combined_audio, real_total_seconds = synthesize_with_pauses(narration_text, tts)
    combined_audio = pydub_normalize(combined_audio)
    print(f"Real measured narration length: {real_total_seconds:.1f}s")

    shot_durations = None
    production_plan = video.get("production_plan")
    if production_plan:
        planned_durations = _parse_shots_with_durations(production_plan)
        if planned_durations:
            planned_total = sum(planned_durations)
            _check_narration_length_plausible(
                real_total_seconds, planned_total, len(split_into_segments(narration_text))
            )
            shot_durations = _scale_shot_durations(planned_durations, real_total_seconds)
            print(f"Computed {len(shot_durations)} real per-shot durations "
                  f"(scaled from planned, summing to {sum(shot_durations):.1f}s).")
        else:
            print("No shots parsed from production_plan yet - skipping shot_durations for now.")
    else:
        print("No production_plan yet on this video - skipping shot_durations for now.")

    raw_wav_path = os.path.join(WORK_DIR, "narration_raw.wav")
    wav_path = os.path.join(WORK_DIR, "narration.wav")
    combined_audio.export(raw_wav_path, format="wav")

    print("Applying slowdown (pitch preserved)")
    import subprocess
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", raw_wav_path, "-filter:a", f"atempo={SLOWDOWN_FACTOR}", wav_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print("ffmpeg error: " + result.stdout.decode(errors="ignore"))
        sys.exit(1)
    os.remove(raw_wav_path)

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

    if shot_durations is not None:
        print("Saving real shot_durations to backend")
        slowdown = float(SLOWDOWN_FACTOR)
        shot_durations = [d / slowdown for d in shot_durations]
        patch_resp = requests.patch(
            f"{RAILWAY_URL}/api/v1/videos/{video_id}",
            json={"shot_durations": shot_durations},
            timeout=30,
        )
        patch_resp.raise_for_status()
        print("shot_durations saved.")


if __name__ == "__main__":
    main()
