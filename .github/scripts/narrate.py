import asyncio
import os
import random
import re
import sys
import time

import edge_tts
import requests
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

RAILWAY_URL = os.environ["RAILWAY_URL"]
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()

# EDGE TTS (reverted 2026-08-09, matching Marius): replaces Chatterbox TTS.
# Chatterbox was ported here 2026-08-04 but never confirmed reliable - its
# first live run (2026-08-08) produced ~4s of audio for a ~555s-planned
# script, a near-total synthesis failure that no exception caught (see
# MIN_PLAUSIBLE_RATIO guard below, added 2026-08-09 after the fact). Edge
# TTS is the same engine already confirmed reliable on Marius, and this is
# a straight revert for this file specifically - narrate.py ran Edge TTS
# before Chatterbox ever replaced it here. Runs on a GitHub-hosted runner
# same as before - plenty of RAM either way, but no longer relying on an
# in-process neural model at all.
# FIX (2026-08-09, later same day): default voice was silently AriaNeural
# (female) despite every brain doc documenting GuyNeural (male) as Nova's
# voice since the original Edge TTS adoption. narrate.yml has no override,
# so this default is what actually ran in production. Corrected to match
# the documented/intended voice.
EDGE_TTS_VOICE = os.environ.get("EDGE_TTS_VOICE", "en-US-GuyNeural")
SLOWDOWN_FACTOR = "0.95"

# VOICE MODULATION FIX (2026-09-04): every sentence was previously
# synthesized with identical rate/pitch, making the narrator sound flat
# and robotic across an entire ~9-minute video. Edge TTS's Communicate
# class accepts per-call `rate` (percent offset) and `pitch` (Hz offset)
# parameters - these were never being passed, so everything defaulted to
# "+0%"/"+0Hz" every time. Each sentence now gets a small randomized
# rate/pitch nudge within a narrow, natural-sounding band (kept modest on
# purpose - wide swings would sound erratic/uncanny, not "expressive").
# This is a pure narration-engine change; it does not touch
# split_into_segments' abbreviation-aware sentence boundaries or the
# pause-insertion logic, both of which are unaffected and unchanged.
VOICE_RATE_VARIATION_PCT = (-4, 5)   # inclusive range, percent offset from base rate
VOICE_PITCH_VARIATION_HZ = (-3, 4)   # inclusive range, Hz offset from base pitch

# FIX (2026-08-10): was alternating 1.0s/2.0s between sentences (average
# ~1.5s, worst-case 2.0s - perceived as ~3s with slowdown/normalize stacked
# on top). Flattened to a constant 1.0s. shot_durations is recomputed from
# the real measured narration length AFTER this runs (see
# _scale_shot_durations below), so shortening pauses here automatically
# shortens the shots too - no separate video-sync fix needed.
PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 1.0

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


def _random_rate_str():
    offset = random.randint(*VOICE_RATE_VARIATION_PCT)
    sign = "+" if offset >= 0 else ""
    return f"{sign}{offset}%"


def _random_pitch_str():
    offset = random.randint(*VOICE_PITCH_VARIATION_HZ)
    sign = "+" if offset >= 0 else ""
    return f"{sign}{offset}Hz"


async def _synthesize_sentence_edge(text, tmp_path, rate="+0%", pitch="+0Hz"):
    communicate = edge_tts.Communicate(text, voice=EDGE_TTS_VOICE, rate=rate, pitch=pitch)
    await communicate.save(tmp_path)


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


# ABBREVIATION-SPLIT FIX (2026-08-29): split_into_segments below split on
# ANY ".", "!", or "?" followed by whitespace - which wrongly treats
# abbreviations and initials as full sentence ends. "Dr. Smith explained"
# was being split into "Dr." and "Smith explained" as if they were two
# separate sentences, each getting its own TTS call AND the full
# inter-sentence pause inserted between them - audible as the narrator
# stopping mid-sentence before continuing (Zia's report: narration "does
# not complete a sentence in one go"). This list covers common
# abbreviations/titles/initials that precede a period without ending the
# sentence; if the word right before the period matches one of these (or
# is a single letter, i.e. an initial), the split is skipped and the
# sentence keeps building instead of being cut there.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "no", "vs",
    "etc", "eg", "ie", "approx", "inc", "ltd", "corp", "co", "u.s",
    "u.k", "u.n", "u.s.a", "a.m", "p.m", "ph.d", "gov", "sen", "rep",
    "capt", "gen", "lt", "col", "maj", "ave", "blvd", "dept",
}


def split_into_segments(narration_text):
    """Splits narration into one segment per real SENTENCE, so a pause gets
    inserted only at genuine sentence boundaries - not after abbreviations,
    titles, or initials that happen to end in a period. Sentence boundary =
    ./!/? followed by whitespace, UNLESS the word immediately before that
    punctuation is a known abbreviation/title or a single letter (an
    initial like "J."), in which case the split is skipped and the
    sentence keeps accumulating."""
    raw_pieces = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    segments = []
    buffer = ""
    for piece in raw_pieces:
        buffer = f"{buffer} {piece}".strip() if buffer else piece
        match = re.search(r"([A-Za-z]+)\.$", buffer)
        if match:
            word = match.group(1).lower()
            if word in _ABBREVIATIONS or len(word) <= 2:
                continue  # not a real sentence end - keep accumulating
        segments.append(buffer.strip())
        buffer = ""
    if buffer.strip():
        segments.append(buffer.strip())
    return [s for s in segments if s] or [narration_text.strip()]


def synthesize_sentence(text, tmp_path):
    rate_str = _random_rate_str()
    pitch_str = _random_pitch_str()
    asyncio.run(_synthesize_sentence_edge(text, tmp_path, rate=rate_str, pitch=pitch_str))
    clip = AudioSegment.from_file(tmp_path)
    # DIAGNOSTIC (2026-08-09): kept from the Chatterbox near-empty-audio
    # bug - logs each segment's real length so a future failure points at
    # the exact sentence(s) that came out wrong, not just the aggregate.
    # Now also logs the rate/pitch used for this segment (2026-09-04 voice
    # modulation fix), so a future "sounds off" report can be diagnosed
    # against the exact values that produced it.
    print(f"  segment ({len(text)} chars, rate={rate_str}, pitch={pitch_str}): "
          f"{len(clip) / 1000.0:.2f}s audio -> {text[:60]!r}")
    return clip


def synthesize_with_pauses(narration_text):
    segments = split_into_segments(narration_text)
    print(f"Narration split into {len(segments)} sentence(s) for pause insertion.")

    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(segments):
        clip = synthesize_sentence(segment, os.path.join(WORK_DIR, f"sent_{i}.mp3"))
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
# per-shot timing. Refuse to trust a narration length this implausible -
# fail loudly here instead of quietly corrupting shot_durations for
# assemble.py to consume later. Kept as a safety net after the Chatterbox
# -> Edge TTS switch, since it's a cheap, engine-agnostic sanity check.
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
            f"means TTS produced near-empty audio for some/all segments - check the "
            f"per-segment lengths logged above for the exact sentence(s) that failed. "
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

    print("Generating speech with Edge TTS (sentence-level, real pauses, per-sentence rate/pitch variation)")
    combined_audio, real_total_seconds = synthesize_with_pauses(narration_text)
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
