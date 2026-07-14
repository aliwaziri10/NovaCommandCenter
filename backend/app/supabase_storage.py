"""
Uploads bytes to Supabase Storage and returns a public URL.

This exists because Railway's local disk is NOT durable storage - files
written there are wiped on container restart/redeploy. Narration audio
and final assembled video were both being stored only on that local
disk, which is why finished videos were silently never reaching YouTube:
the file would vanish before the next scheduled pipeline step (assembly
or upload) ran.
"""

import requests
from app.config import settings

BUCKET = "nova-media"


def upload_to_storage(path_in_bucket, content_bytes, content_type):
    """Uploads content_bytes to Supabase Storage at path_in_bucket
    (upserting if it already exists) and returns the public URL. Raises
    RuntimeError with Supabase's actual error text on failure - this must
    never fail silently, since a silent failure here is exactly how this
    problem stayed hidden for days last time."""
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SECRET_KEY not set on this Railway service - "
            "durable storage upload cannot proceed."
        )

    upload_url = f"{settings.supabase_url}/storage/v1/object/{BUCKET}/{path_in_bucket}"
    resp = requests.put(
        upload_url,
        headers={
            "apikey": settings.supabase_secret_key,
            "Authorization": f"Bearer {settings.supabase_secret_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        data=content_bytes,
        timeout=300,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Supabase Storage upload failed ({resp.status_code}): {resp.text}")

    return f"{settings.supabase_url}/storage/v1/object/public/{BUCKET}/{path_in_bucket}"
