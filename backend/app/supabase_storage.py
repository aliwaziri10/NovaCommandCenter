"""
Uploads bytes or a file-like stream to Supabase Storage and returns a
public URL.

This exists because Railway's local disk is NOT durable storage - files
written there are wiped on container restart/redeploy. Narration audio
and final assembled video were both being stored only on that local
disk, which is why finished videos were silently never reaching
YouTube: the file would vanish before the next scheduled pipeline step
(assembly or upload) ran.
"""

import requests
from app.config import settings

BUCKET = "nova-media"


def upload_to_storage(path_in_bucket, content_bytes, content_type, content_length=None):
    """Uploads content_bytes (or a file-like/stream object) to Supabase
    Storage at path_in_bucket (upserting if it already exists) and
    returns the public URL.

    content_bytes may be raw bytes, OR a file-like object opened for
    reading (e.g. FastAPI's UploadFile.file). Passing a file-like object
    lets `requests` stream the upload in chunks instead of holding the
    whole thing as a second full-size bytes object in RAM on top of
    whatever buffer already holds it - this matters on Render's free
    tier, where a large CRF-encoded final render can push memory usage
    into OOM territory if it gets duplicated in memory during upload.

    If content_length is known (e.g. computed from the source file's
    size), pass it so the Content-Length header can be set explicitly -
    Supabase Storage's PUT endpoint is more reliable with an explicit
    Content-Length than with chunked transfer encoding.

    Raises RuntimeError with Supabase's actual error text on failure -
    this must never fail silently, since a silent failure here is
    exactly how this problem stayed hidden for days last time.
    """
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SECRET_KEY not set on this Render service - "
            "durable storage upload cannot proceed."
        )

    upload_url = f"{settings.supabase_url}/storage/v1/object/{BUCKET}/{path_in_bucket}"

    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    if content_length is not None:
        headers["Content-Length"] = str(content_length)

    # TIMEOUT MATCHED (2026-08-30): was 300s. assemble.py's client-side
    # POST to this backend's /upload/video/{id} was raised 300->600s the
    # same session (larger CRF-encoded files, no artificial size budget
    # anymore). This inner PUT to Supabase is the leg that actually
    # transfers the bytes - leaving it at 300 while the outer timeout
    # allows 600 meant this could time out first on a large file and
    # surface as an opaque 502 without ever reaching the outer timeout.
    resp = requests.put(
        upload_url,
        headers=headers,
        data=content_bytes,
        timeout=600,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Supabase Storage upload failed ({resp.status_code}): {resp.text}")

    return f"{settings.supabase_url}/storage/v1/object/public/{BUCKET}/{path_in_bucket}"
