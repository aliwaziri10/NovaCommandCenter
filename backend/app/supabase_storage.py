"""
Uploads bytes or a file-like stream to Backblaze B2 (via its S3-compatible
API) and returns a public URL.

MIGRATED 2026-09-02: previously uploaded to Supabase Storage, but
Supabase's Free plan enforces a hard 50MB Global file size limit that
cannot be raised past 50MB by any bucket-level setting - confirmed
directly against Supabase's own docs. Nova's CRF20-encoded 1080p
renders (600-750MB) could never fit through that ceiling regardless of
any bucket-level file_size_limit setting, including the 200MB one set
on 2026-08-29 (which was silently capped at 50MB underneath).

Moved to Backblaze B2 instead: 10GB free storage (permanent, no
expiry), no per-file size cap, free egress up to 3x stored data/month
(fixes the separate Egress Exceeded problem too), no credit card
required to sign up.

This module's filename and function name are kept the same
(supabase_storage.py / upload_to_storage) so no other file in the
codebase needed to change its import - only this file's internals
changed. The bucket is Public (not Private) because assemble.py
(running on a separate GitHub Actions machine) does a plain
unauthenticated HTTP GET to download narration/video files by URL -
same behavior as the old public Supabase bucket.

This exists because Render's local disk is NOT durable storage - files
written there are wiped on container restart/redeploy. Narration audio
and final assembled video both need to land in durable external
storage, not local disk.
"""

import boto3
from botocore.config import Config as BotoConfig
from app.config import settings


def _b2_client():
    if not settings.b2_endpoint_url or not settings.b2_key_id or not settings.b2_application_key:
        raise RuntimeError(
            "B2_ENDPOINT_URL / B2_KEY_ID / B2_APPLICATION_KEY not set on this "
            "Render service - durable storage upload cannot proceed."
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.b2_endpoint_url}",
        aws_access_key_id=settings.b2_key_id,
        aws_secret_access_key=settings.b2_application_key,
        config=BotoConfig(signature_version="s3v4"),
    )


def upload_to_storage(path_in_bucket, content_bytes, content_type, content_length=None):
    """Uploads content_bytes (or a file-like/stream object) to the B2
    bucket at path_in_bucket (overwriting if it already exists) and
    returns the public URL.

    content_bytes may be raw bytes, OR a file-like object opened for
    reading (e.g. FastAPI's UploadFile.file) - boto3's put_object
    accepts either directly as Body, so no separate streaming code path
    is needed here.

    content_length is accepted for backward compatibility with the
    existing call sites (upload_router.py etc.) but is not required by
    boto3/B2 - kept as a no-op parameter so no caller needed to change
    its function call.

    Raises RuntimeError with B2's actual error text on failure - this
    must never fail silently, since a silent failure here is exactly
    how a past version of this problem stayed hidden for days.
    """
    bucket = settings.b2_bucket_name
    client = _b2_client()

    try:
        client.put_object(
            Bucket=bucket,
            Key=path_in_bucket,
            Body=content_bytes,
            ContentType=content_type,
        )
    except Exception as e:
        raise RuntimeError(f"Backblaze B2 upload failed: {e}")

    return f"https://{settings.b2_endpoint_url}/{bucket}/{path_in_bucket}"
