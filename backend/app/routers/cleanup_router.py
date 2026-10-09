"""
One-off Backblaze B2 cleanup (2026-10-09).

Deletes every file in the B2 bucket that belongs to a video already live on
YouTube (videos.youtube_video_id is set). Files of unfinished videos are
never touched; files matching no video are only reported.

Usage (browser, GET):
  .../api/v1/cleanup/b2-uploaded            -> report only (nothing deleted)
  .../api/v1/cleanup/b2-uploaded?confirm=yes -> actually deletes
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models.video import Video
from app.supabase_storage import _b2_client

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


def _gb(n):
    return round(n / (1024 ** 3), 2)


@router.get("/b2-uploaded")
def cleanup_b2_uploaded(confirm: str = "", db: Session = Depends(get_db)):
    rows = db.query(Video.id, Video.youtube_video_id).all()
    uploaded_ids = {str(r[0]) for r in rows if r[1]}
    other_ids = {str(r[0]) for r in rows if not r[1]}

    client = _b2_client()
    bucket = settings.b2_bucket_name

    total_files = total_bytes = 0
    kept_files = kept_bytes = orphan_files = orphan_bytes = 0
    to_delete, del_bytes = [], 0

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            total_files += 1
            total_bytes += size
            if any(i in key for i in other_ids):
                kept_files += 1
                kept_bytes += size
            elif any(i in key for i in uploaded_ids):
                to_delete.append(key)
                del_bytes += size
            else:
                orphan_files += 1
                orphan_bytes += size

    result = {
        "bucket": bucket,
        "videos_uploaded": len(uploaded_ids),
        "videos_not_uploaded_protected": len(other_ids),
        "bucket_files_before": total_files,
        "bucket_gb_before": _gb(total_bytes),
        "protected_files": kept_files,
        "protected_gb": _gb(kept_bytes),
        "orphan_files_left_alone": orphan_files,
        "orphan_gb_left_alone": _gb(orphan_bytes),
        "to_delete_files": len(to_delete),
        "to_delete_gb": _gb(del_bytes),
    }

    if confirm != "yes":
        result["mode"] = "REPORT ONLY - nothing deleted. Add ?confirm=yes to the URL to delete."
        return result

    deleted = 0
    errors = []
    for i in range(0, len(to_delete), 1000):
        batch = to_delete[i:i + 1000]
        resp = client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
        )
        errs = resp.get("Errors", [])
        deleted += len(batch) - len(errs)
        errors.extend(errs[:5])

    result["mode"] = "DELETED"
    result["files_deleted"] = deleted
    result["gb_freed"] = _gb(del_bytes)
    result["bucket_gb_after"] = _gb(total_bytes - del_bytes)
    if errors:
        result["errors_sample"] = errors
    return result
