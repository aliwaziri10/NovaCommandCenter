"""
Nova Command Center - YouTube Upload Agent
Finds the oldest video with status "assembled" and no youtube_video_id,
downloads it from Render's own storage, uploads it to YouTube via the
Data API v3 using a stored OAuth refresh token, then marks it uploaded.

Uploads are set to 'public'. Sets containsSyntheticMedia = True on every
upload, per YouTube's AI-disclosure requirement, since all content here
is AI-generated.

Unlike Marius (which talks to Supabase REST directly), Nova's video files
and metadata live behind its own FastAPI backend (now on Render), so this
script talks to that backend's REST API instead.

Render's free tier spins the backend down after inactivity. The first
request after a cold start can take 30-90+ seconds just to wake it up.
wake_up_backend() below retries with a long timeout before doing real work.
"""

import os
import time
import requests

RAILWAY_URL = os.environ["RAILWAY_URL"]
YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

BACKEND_TIMEOUT = 90  # was 30 — too short for a cold Render free-tier instance


def wake_up_backend(max_attempts=4):
    """Ping the backend until it responds, to survive Render cold starts."""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(f"{RAILWAY_URL}/api/v1/videos", timeout=BACKEND_TIMEOUT)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            print(f"Backend not awake yet (attempt {attempt}/{max_attempts}): {e}")
            if attempt == max_attempts:
                raise
            time.sleep(10)


def get_access_token():
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        print(f"TOKEN REFRESH ERROR {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_next_ready_video():
    resp = wake_up_backend()
    videos = resp.json()
    candidates = [
        v for v in videos
        if v.get("status") == "assembled" and not v.get("youtube_video_id")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    return candidates[0]


def download_file(url, out_path):
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def build_description(production_plan):
    snippet = (production_plan or "").strip()[:1500]
    return f"{snippet}\n\n#history #alternatehistory #alternateearth"


def upload_to_youtube(access_token, video_path, title, description):
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }

    file_size = os.path.getsize(video_path)

    init_resp = requests.post(
        f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        },
        json=metadata,
        timeout=60,
    )
    if init_resp.status_code >= 400:
        print(f"UPLOAD INIT ERROR {init_resp.status_code}: {init_resp.text}")
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    with open(video_path, "rb") as f:
        file_bytes = f.read()

    put_resp = requests.put(
        upload_url,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
        },
        data=file_bytes,
        timeout=600,
    )
    if put_resp.status_code >= 400:
        print(f"UPLOAD PUT ERROR {put_resp.status_code}: {put_resp.text}")
    put_resp.raise_for_status()
    return put_resp.json()["id"]


def mark_uploaded(video_id, youtube_id):
    resp = requests.patch(
        f"{RAILWAY_URL}/api/v1/videos/{video_id}",
        json={"status": "uploaded", "youtube_video_id": youtube_id},
        timeout=BACKEND_TIMEOUT,
    )
    if resp.status_code >= 400:
        print(f"MARK UPLOADED ERROR {resp.status_code}: {resp.text}")
    resp.raise_for_status()


def main():
    video = get_next_ready_video()
    if not video:
        print("No videos ready for YouTube upload. Nothing to do.")
        return

    video_id = video["id"]
    print(f"Working on video {video_id}")

    title = video.get("title") or "Alternate Earth"
    description = build_description(video.get("production_plan", ""))

    video_path = "/tmp/upload_video.mp4"
    download_file(f"{RAILWAY_URL}/api/v1/download/videos/{video_id}", video_path)

    access_token = get_access_token()
    youtube_id = upload_to_youtube(access_token, video_path, title, description)
    print(f"Uploaded to YouTube (PUBLIC): https://youtube.com/watch?v={youtube_id}")

    mark_uploaded(video_id, youtube_id)
    print("Done.")


if __name__ == "__main__":
    main()
