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
            "privacyStatus": "public",
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
    print(f"SUCCESS: uploaded as https://youtube.com/watch?v={youtube_video_id}")

    print("Marking video as uploaded in backend...")
    # NOTE: there is no dedicated /mark-uploaded endpoint on this backend -
    # that route was never built (confirmed by reading main.py's registered
    # routers). The generic CRUD router DOES support PATCH on /videos/{id},
    # so we use that instead.
    mark_resp = requests.patch(
        f"{RAILWAY_URL}/api/v1/videos/{video_id}",
        json={"status": "uploaded", "youtube_video_id": youtube_video_id},
        timeout=60,
    )
    if mark_resp.status_code >= 400:
        print(f"WARNING: upload succeeded but failed to mark backend as uploaded: {mark_resp.status_code} {mark_resp.text}")
    else:
        print(f"Backend updated: video {video_id} marked status=uploaded, youtube_video_id={youtube_video_id}.")


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
