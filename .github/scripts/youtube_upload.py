import os
import sys
import time

import requests

RAILWAY_URL = os.environ["RAILWAY_URL"]  # name is legacy - this actually points to Render now
YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()

# UPDATED (2026-09-02): cleanup target switched from Supabase Storage to a
# GitHub Release asset, matching assemble.py's commit 6291ca5 (2026-09-02)
# switch of the upload destination itself. This deletes the finished video
# from the 'nova-video-storage' release on this repo now that it has been
# confirmed uploaded to YouTube and the backend record marked
# status=uploaded - same idempotent, best-effort, never-raise cleanup
# contract as the previous Supabase version. Without this change, assets
# would silently never be deleted (the old Supabase-delete call 404s and
# is treated as success, so the bug would be invisible in logs).
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
RELEASE_TAG = "nova-video-storage"

BACKEND_TIMEOUT = 120  # Render cold starts can run past 90s
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

# Nova's channel. Both this channel and "Erased" (used by the separate Marius
# project) are managed by the SAME Google account (ziawaziri@gmail.com), so a
# wrong-credential-pair upload landing on the wrong channel is a real,
# recurring risk here - not a hypothetical one. This is checked BEFORE
# downloading or uploading anything, so a wrong YT_CLIENT_ID/YT_REFRESH_TOKEN
# pair fails loudly and immediately instead of silently posting to Erased.
EXPECTED_CHANNEL_TITLE = "Alternate Earth"

# UPDATED (2026-08-16): uploads are private, not public. Zia flagged real
# quality problems (generic opening frame, per-scene freeze-holds, a 30-40s
# end-of-video freeze, character age drift) that are still being fixed and
# tested. Every upload lands as private until Zia personally reviews it in
# YouTube Studio and flips it public himself. Do not change this back to
# "public" without an explicit instruction from Zia.
# FIX (2026-08-29): this was hardcoded to "public" despite the comment above
# saying "private" - every upload since 2026-08-16 has actually been going
# out public and unreviewed. Corrected to match the intended behavior.
UPLOAD_PRIVACY_STATUS = "private"

# --- Required metadata that was previously missing on every Nova upload ---
# FIX (2026-08-29): uploads had a title only - no fallback description, no
# "made for kids" declaration, no AI-generated-content disclosure. YouTube
# requires the made-for-kids answer on every upload (silently defaults if
# omitted) and strongly expects synthetic/altered media to be disclosed.
# These are now always set explicitly, never left for manual fixing later.
SELF_DECLARED_MADE_FOR_KIDS = False  # Alternate Earth is not child-directed content
CONTAINS_SYNTHETIC_MEDIA = True      # AI-generated visuals/voiceover - always disclosed

# FIX (2026-09-03): this was the ONLY description text ever used - the
# backend's video.description field is never populated anywhere in Nova's
# pipeline (confirmed: no agent writes it), so every single upload silently
# used this exact generic template with zero per-video content, unlike
# Marius (scripts/youtube_upload.py's build_description()) which builds a
# real per-video description from the actual narration/script text. Zia
# flagged this directly by comparing Nova's and Marius's YouTube Studio
# description fields side by side. This string is now ONLY the last-resort
# fallback when script_content genuinely can't be fetched (see
# _build_story_description below) - not the default outcome.
FALLBACK_DESCRIPTION = (
    "This video explores a speculative \"what if\" scenario as part of the "
    "Alternate Earth series.\n\n"
    "This video was made using AI-generated visuals and AI narration.\n\n"
    "Subscribe for more speculative history and alternate-timeline documentaries."
)
AI_DISCLOSURE_LINE = "This video was made using AI-generated visuals and AI narration."

# ADDED (2026-08-30): assemble.py now mixes a royalty-free chapter music bed
# into every video (NOVA_REBUILD_HANDOFF.md item #6), sourced from Kevin
# MacLeod / incompetech.com under Creative Commons BY 3.0 - the license
# requires attribution wherever the video is published. assemble.py has no
# way to write to the video's YouTube description itself (that's this
# script's job, at upload time), so this line is always included here,
# unconditionally, alongside the AI-disclosure line. It's included even on
# a run where every chapter track happened to fail to download (see
# assemble.py's _build_music_bed - a per-video, per-segment silent
# degrade), since this script has no reliable signal on whether any given
# uploaded video actually ended up with music in it - the license
# obligation is cheap and unconditional attribution is the safe default,
# not a real cost, whereas omitting it on a video that DID get music
# would be a real compliance gap.
MUSIC_ATTRIBUTION_LINE = (
    "Music by Kevin MacLeod (incompetech.com), licensed under Creative "
    "Commons: By Attribution 3.0 (creativecommons.org/licenses/by/3.0/)"
)

# ADDED (2026-09-03): real per-video description, ported from Marius's
# scripts/youtube_upload.py build_description() - truncates the actual
# script/narration text to a sentence boundary instead of a hard character
# cut, so the description reads as real prose, not text chopped mid-word.
DESCRIPTION_SNIPPET_LIMIT = 1500

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


def _build_story_description(script_content):
    """ADDED (2026-09-03): builds a real per-video description from the
    actual script/narration text, ported from Marius's build_description().
    Truncates at a sentence boundary (not a hard character cut) so the
    result reads as real prose. Returns None if script_content is missing/
    empty - caller falls back to FALLBACK_DESCRIPTION in that case, same
    safety net as before this fix.
    """
    text = (script_content or "").strip()
    if not text:
        return None

    if len(text) > DESCRIPTION_SNIPPET_LIMIT:
        snippet = text[:DESCRIPTION_SNIPPET_LIMIT]
        last_boundary = max(
            snippet.rfind(". "),
            snippet.rfind(".\n"),
            snippet.rfind("! "),
            snippet.rfind("? "),
        )
        if last_boundary > 0:
            snippet = snippet[: last_boundary + 1]
        else:
            last_space = snippet.rfind(" ")
            snippet = (snippet[:last_space] if last_space > 0 else snippet) + "..."
    else:
        snippet = text

    return (
        f"{snippet}\n\n"
        f"Subscribe for more speculative history and alternate-timeline "
        f"documentaries - Alternate Earth explores what could have been."
    )


def _build_final_description(raw_description, chapters_block, script_content):
    """Guarantees every upload has a real, non-empty description containing
    the AI-content disclosure line and the required music-attribution line.

    FIX (2026-09-03): previously only ever used raw_description (the
    backend's video.description field, which nothing in Nova's pipeline
    ever populates) and fell straight to the generic FALLBACK_DESCRIPTION
    on every single upload - confirmed by Zia comparing Nova's and Marius's
    YouTube Studio description fields directly. Now tries, in order: (1)
    raw_description if the backend ever does have one, (2) a real per-video
    description built from script_content (see _build_story_description),
    (3) the generic fallback only as a genuine last resort.
    """
    description = (raw_description or "").strip()
    if not description:
        description = _build_story_description(script_content) or FALLBACK_DESCRIPTION

    if AI_DISCLOSURE_LINE not in description:
        description = description + "\n\n" + AI_DISCLOSURE_LINE

    if MUSIC_ATTRIBUTION_LINE not in description:
        description = description + "\n\n" + MUSIC_ATTRIBUTION_LINE

    if chapters_block:
        description = chapters_block + "\n\n" + description

    return description


def _github_api_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _delete_from_github_release(video_id):
    """UPDATED (2026-09-02): deletes the finished video's GitHub Release
    asset (release tag 'nova-video-storage', asset name '{video_id}.mp4')
    now that it has been confirmed uploaded to YouTube and the backend
    record has been marked status=uploaded - see assemble.py's
    _upload_final_video_to_github_release for how the asset got there.
    Only called from main() after both the YouTube upload AND the backend
    status PATCH have succeeded.

    Best-effort: prints a clear warning on failure but does NOT raise - a
    cleanup failure should never be treated as an upload failure (the
    video is already safely on YouTube by this point), and the next run's
    cleanup attempt for a different video isn't blocked by one stale asset
    failing to delete. An asset that fails to delete here just sits on the
    release until manually cleared or retried - it does not silently
    vanish or corrupt anything.
    """
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("WARNING: cleanup skipped - GITHUB_TOKEN or GITHUB_REPOSITORY not set.")
        return

    asset_name = f"{video_id}.mp4"
    try:
        get_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/tags/{RELEASE_TAG}"
        resp = requests.get(get_url, headers=_github_api_headers(), timeout=30)
        if resp.status_code == 404:
            print(f"Cleanup: release '{RELEASE_TAG}' not found - nothing to delete for {asset_name}.")
            return
        if resp.status_code >= 400:
            print(f"WARNING: cleanup failed - could not look up release '{RELEASE_TAG}' ({resp.status_code}): {resp.text[:300]}.")
            return

        asset = next((a for a in resp.json().get("assets", []) if a.get("name") == asset_name), None)
        if not asset:
            print(f"Cleanup: no asset named {asset_name} on release '{RELEASE_TAG}' - nothing to delete.")
            return

        del_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/assets/{asset['id']}"
        del_resp = requests.delete(del_url, headers=_github_api_headers(), timeout=30)
        if del_resp.status_code >= 400 and del_resp.status_code != 404:
            print(
                f"WARNING: cleanup failed - could not delete {asset_name} from release "
                f"'{RELEASE_TAG}' ({del_resp.status_code}): {del_resp.text[:300]}. "
                f"Asset will remain until manually cleared."
            )
        else:
            print(f"Cleanup: deleted {asset_name} from GitHub Release '{RELEASE_TAG}' (video is now only on YouTube).")
    except requests.RequestException as e:
        print(f"WARNING: cleanup failed - network error deleting {asset_name} from release '{RELEASE_TAG}': {e}. Asset will remain until manually cleared.")


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
            print(f"Backend not awake yet (attempt {attempt}/{max_attempts}): read timeout after {BACKEND_TIMEOUT}s")
        except requests.exceptions.ConnectionError as e:
            print(f"Backend not reachable yet (attempt {attempt}/{max_attempts}): {e}")

        if attempt < max_attempts:
            wait = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
            print(f"Waiting {wait}s before retry...")
            time.sleep(wait)

    raise RuntimeError(
        f"Backend at {RAILWAY_URL} did not respond after {max_attempts} attempts. "
        "Check Render dashboard for deploy/crash status."
    )


def _get_youtube_access_token():
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _get_authorized_channel(access_token):
    """Asks YouTube which channel the current access token is actually
    authorized for. This is how we tell Ali's two client_id/refresh_token
    pairs apart without having to do a live upload to find out."""
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"part": "snippet", "mine": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise RuntimeError(
            "YouTube API returned no channel for these credentials - the token "
            "may be invalid, expired, or missing the youtube.upload/youtube.readonly scope."
        )
    channel = items[0]
    return channel["id"], channel["snippet"]["title"]


def _find_next_video_to_upload(videos):
    candidates = [
        v for v in videos
        if v.get("status") == "assembled" and not v.get("youtube_video_id")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    return candidates[0]


def _upload_to_youtube(video_bytes, title, description, access_token):
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": UPLOAD_PRIVACY_STATUS,
            "selfDeclaredMadeForKids": SELF_DECLARED_MADE_FOR_KIDS,
            "containsSyntheticMedia": CONTAINS_SYNTHETIC_MEDIA,
        },
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers={**headers, "X-Upload-Content-Type": "video/mp4"},
        json=metadata,
        timeout=60,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    upload_resp = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4"},
        data=video_bytes,
        timeout=600,
    )
    upload_resp.raise_for_status()
    return upload_resp.json()


def main():
    print("Getting YouTube access token and verifying which channel it's authorized for...")
    access_token = _get_youtube_access_token()
    channel_id, channel_title = _get_authorized_channel(access_token)
    print(f"These credentials are authorized for channel: {channel_title!r} ({channel_id})")

    if channel_title.strip().lower() != EXPECTED_CHANNEL_TITLE.lower():
        raise RuntimeError(
            f"REFUSING TO UPLOAD: these credentials authorize {channel_title!r}, not the "
            f"expected {EXPECTED_CHANNEL_TITLE!r}. This is the wrong YT_CLIENT_ID/YT_REFRESH_TOKEN "
            f"pair for Nova. Fix: on youtube.com signed in as ziawaziri@gmail.com, switch the active "
            f"channel to {EXPECTED_CHANNEL_TITLE}, redo the OAuth consent flow to get a matching "
            f"client_id/refresh_token pair, then update the YT_CLIENT_ID/YT_CLIENT_SECRET/"
            f"YT_REFRESH_TOKEN secrets on this repo. No video was downloaded or uploaded."
        )
    print(f"Channel verified ({EXPECTED_CHANNEL_TITLE}) - proceeding.")

    print(f"Uploads will be marked '{UPLOAD_PRIVACY_STATUS}' (Zia reviews and publishes manually).")
    print(f"Made for kids: {SELF_DECLARED_MADE_FOR_KIDS} | AI-content disclosure: {CONTAINS_SYNTHETIC_MEDIA}")

    print("Waking backend and fetching video list...")
    resp = wake_up_backend()
    resp.raise_for_status()
    videos = resp.json()

    video_id = VIDEO_ID
    if video_id:
        video = next((v for v in videos if v.get("id") == video_id), None)
        if not video:
            print(f"ERROR: video_id {video_id} not found")
            sys.exit(1)
    else:
        print("No VIDEO_ID provided - auto-selecting next assembled video ready for upload...")
        video = _find_next_video_to_upload(videos)
        if not video:
            print("No assembled videos currently waiting for upload. Exiting cleanly.")
            return
        video_id = video["id"]
        print(f"Auto-selected video_id: {video_id}")

    title = video.get("title") or "Untitled"
    description = video.get("description") or ""

    print("Fetching script content (for real description + chapter markers)...")
    shot_durations = video.get("shot_durations")
    script_content = None
    script_id = video.get("script_id")
    if script_id:
        try:
            script_resp = requests.get(f"{RAILWAY_URL}/api/v1/scripts/{script_id}", timeout=BACKEND_TIMEOUT)
            script_resp.raise_for_status()
            script_content = script_resp.json().get("content")
        except Exception as e:
            print(f"Could not fetch script for description/chapter titles: {e}")

    chapters_block = _build_chapters_block(shot_durations, script_content)
    if chapters_block:
        print("Chapter markers added to description:")
        print(chapters_block)
    else:
        print("Proceeding without chapter markers.")

    description = _build_final_description(description, chapters_block, script_content)
    print("Final description that will be uploaded:")
    print(description)

    print(f"Downloading final video file for {video_id}...")
    file_resp = requests.get(
        f"{RAILWAY_URL}/api/v1/download/videos/{video_id}",
        timeout=300,
    )
    file_resp.raise_for_status()
    video_bytes = file_resp.content
    print(f"Downloaded {len(video_bytes)} bytes.")

    print("Uploading to YouTube...")
    result = _upload_to_youtube(video_bytes, title, description, access_token)
    youtube_video_id = result.get("id")
    print(f"SUCCESS: uploaded (privacyStatus={UPLOAD_PRIVACY_STATUS}) as https://youtube.com/watch?v={youtube_video_id}")

    print("Marking video as uploaded in backend...")
    mark_resp = requests.patch(
        f"{RAILWAY_URL}/api/v1/videos/{video_id}",
        json={"status": "uploaded", "youtube_video_id": youtube_video_id},
        timeout=60,
    )

    if mark_resp.status_code >= 400:
        print(f"WARNING: upload succeeded but failed to mark backend as uploaded: {mark_resp.status_code} {mark_resp.text}")
    else:
        print(f"Backend updated: video {video_id} marked status=uploaded, youtube_video_id={youtube_video_id}.")
        _delete_from_github_release(video_id)

    topic_id = video.get("topic_id")
    if topic_id:
        topic_resp = requests.patch(
            f"{RAILWAY_URL}/api/v1/topics/{topic_id}",
            json={"status": "used"},
            timeout=60,
        )
        if topic_resp.status_code >= 400:
            print(f"WARNING: upload succeeded but failed to mark topic {topic_id} as used: {topic_resp.status_code} {topic_resp.text}")
        else:
            print(f"Backend updated: topic {topic_id} marked status=used.")
    else:
        print("WARNING: video has no topic_id - cannot mark topic as used.")


def _print_failure_summary(exc):
    import traceback
    tb = traceback.extract_tb(exc.__traceback__)
    location = "unknown"
    for frame in tb:
        if frame.filename.endswith("youtube_upload.py"):
            location = f"{frame.name}() line {frame.lineno}"
    print("\n" + "=" * 60)
    print("FAILURE SUMMARY (read this first)")
    print("=" * 60)
    print("Script:        youtube_upload.py")
    print(f"Failed in:     {location}")
    print(f"Error type:    {type(exc).__name__}")
    print(f"Error message: {str(exc)[:400]}")
    print(f"RAILWAY_URL:   {RAILWAY_URL}")
    print(f"VIDEO_ID:      {VIDEO_ID or '(auto-select)'}")
    print("=" * 60)
    print("Full traceback follows below for reference.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _print_failure_summary(e)
        raise
