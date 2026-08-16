import os
import sys
import time

import requests

RAILWAY_URL = os.environ["RAILWAY_URL"]  # name is legacy - this actually points to Render now
YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()

BACKEND_TIMEOUT = 120  # Render cold starts can run past 90s
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

# Nova's channel. Both this channel and "Erased" (used by the separate Marius
# project) are managed by the SAME Google account (ziawaziri@gmail.com), so a
# wrong-credential-pair upload landing on the wrong channel is a real,
# recurring risk here - not a hypothetical one. This is checked BEFORE
# downloading or uploading anything, so a wrong YT_CLIENT_ID/YT_REFRESH_TOKEN
# pair fails loudly and immediately instead of silently posting to Erased.
EXPECTED_CHANNEL_TITLE = "Alternate Earth"

# UPDATED (2026-08-16): uploads are now PRIVATE, not public. Zia flagged real
# quality problems (generic opening frame, per-scene freeze-holds, a 30-40s
# end-of-video freeze, character age drift) that are still being fixed and
# tested. Every upload lands as private until Zia personally reviews it in
# YouTube Studio and flips it public himself. Do not change this back to
# "public" without an explicit instruction from Zia.
UPLOAD_PRIVACY_STATUS = "private"

# --- Chapter markers (added 2026-08-02) ---
# YouTube requires: first chapter at 0:00, at least 3 chapters, each chapter
# at least 10 seconds long. We build chapters from the REAL shot_durations
# narrate.py already measures and saves (not the AI's guessed durations),
# so timestamps line up with the actual uploaded file. Titles are generated
# from the script content so they're curiosity-driven, not generic "Part 2"
# labels. If shot_durations or script content are missing, or the video is
# too short for 3 valid 10s+ chapters, chapters are skipped entirely and the
# upload proceeds exactly as before - this feature can never block an upload.
NUM_CHAPTERS_TARGET = 5
MIN_CHAPTER_SECONDS = 10
POLLINATIONS_TEXT_URL = "https://gen.pollinations.ai/text"
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY")

CHAPTER_TITLE_SYSTEM_PROMPT = (
    "You write YouTube chapter titles for a cinematic alternate-history 'what if' "
    "video. Given a script and a number of chapters, output exactly that many "
    "short chapter titles, one per line, in order, and nothing else - no numbering, "
    "no extra text, no explanations. Each title must be curiosity-driven and "
    "specific to what actually happens at that point in the story (a name, an "
    "event, a turning point, a consequence) - never generic labels like 'Part 1', "
    "'Introduction', or 'Conclusion'. Keep each title under 45 characters."
)


def _format_timestamp(total_seconds: float) -> str:
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _group_shots_into_chapters(shot_durations, num_chapters):
    """Groups per-shot durations into num_chapters contiguous blocks, keeping
    each block as close to equal-length as possible, and returns the start
    timestamp (in seconds) of each block. Returns None if the video is too
    short to produce num_chapters valid (>= MIN_CHAPTER_SECONDS) chapters."""
    total = sum(shot_durations)
    if total < MIN_CHAPTER_SECONDS * 3:
        return None

    target_len = total / num_chapters
    starts = [0.0]
    running = 0.0
    chapter_elapsed = 0.0
    for d in shot_durations:
        running += d
        chapter_elapsed += d
        if chapter_elapsed >= target_len and len(starts) < num_chapters:
            starts.append(running)
            chapter_elapsed = 0.0

    # Drop any chapter that would end up shorter than MIN_CHAPTER_SECONDS
    # (can happen with the last chapter if shots don't divide evenly).
    cleaned = [starts[0]]
    for s in starts[1:]:
        if s - cleaned[-1] >= MIN_CHAPTER_SECONDS:
            cleaned.append(s)

    if len(cleaned) < 3:
        return None
    return cleaned


def _generate_chapter_titles(script_content, num_chapters):
    prompt = (
        f"Script:\n\n{script_content}\n\n"
        f"Output exactly {num_chapters} chapter titles for this video, one per line, "
        f"in story order, evenly spaced across the whole script from beginning to end."
    )
    url = f"{POLLINATIONS_TEXT_URL}/{requests.utils.quote(prompt)}"
    params = {"model": "openai", "system": CHAPTER_TITLE_SYSTEM_PROMPT, "temperature": 0.8}
    if POLLINATIONS_API_KEY:
        params["key"] = POLLINATIONS_API_KEY
    for _ in range(3):
        try:
            resp = requests.get(url, params=params, timeout=60)
            raw = resp.text.strip()
            if raw.startswith('{"role"') or '"reasoning"' in raw[:200] or raw.startswith('{"error"'):
                continue
            lines = [l.strip(" -*\t") for l in raw.splitlines() if l.strip()]
            lines = [l for l in lines if l]
            if len(lines) >= num_chapters:
                return lines[:num_chapters]
        except Exception:
            continue
    return None


def _build_chapters_block(shot_durations, script_content):
    """Returns a YouTube-formatted chapters block (string) to prepend to the
    description, or None if chapters can't be safely built."""
    if not shot_durations or not script_content:
        print("Chapter markers skipped: missing shot_durations or script content.")
        return None

    starts = _group_shots_into_chapters(shot_durations, NUM_CHAPTERS_TARGET)
    if not starts:
        print("Chapter markers skipped: video too short for 3+ valid chapters.")
        return None

    titles = _generate_chapter_titles(script_content, len(starts))
    if not titles:
        print("Chapter markers skipped: title generation failed after 3 attempts.")
        return None

    lines = [f"{_format_timestamp(s)} {t}" for s, t in zip(starts, titles)]
    return "\n".join(lines)


def wake_up_backend(max_attempts=4):
    """
    Wakes a sleeping Render free-tier instance before hitting the real endpoint.
    Uses growing backoff between attempts instead of firing back-to-back,
    since a cold instance needs time to boot before it can even accept
    a new connection.
    """
    backoff_seconds = [10, 20, 40, 60]

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(
                f"{RAILWAY_URL}/api/v1/videos",
                timeout=BACKEND_TIMEOUT,
            )
            return resp
        except requests.exceptions.ReadTimeout:
