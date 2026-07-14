import os
import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.video import Video
from app.supabase_storage import upload_to_storage

ASSEMBLY_SECRET = os.environ.get("ASSEMBLY_SECRET")

router = APIRouter(prefix="/upload", tags=["upload"])


def verify_assembly_secret(x_assembly_secret: str = Header(None)):
    if not ASSEMBLY_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured: ASSEMBLY_SECRET not set")
    if x_assembly_secret != ASSEMBLY_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Assembly-Secret header")


@router.post("/narration/{video_id}")
async def upload_narration(video_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video_id")

    video = db.query(Video).filter(Video.id == vid).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    contents = await file.read()

    # Uploaded to Supabase Storage (durable) instead of Railway's local disk.
    # Railway's local filesystem is NOT durable - it is wiped on every
    # restart/redeploy. Storing narration/final video only there was the
    # root cause of videos silently never reaching YouTube: the file
    # would vanish before the next scheduled pipeline step ran.
    audio_url = upload_to_storage(f"narration/{video_id}.mp3", contents, "audio/mpeg")

    video.audio_path = audio_url
    db.commit()
    db.refresh(video)

    return {
        "video_id": video_id,
        "audio_path": audio_url,
        "file_size_bytes": len(contents),
    }


@router.post("/video/{video_id}")
async def upload_video(
    video_id: str,
    file: UploadFile = File(...),
    x_assembly_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    verify_assembly_secret(x_assembly_secret)

    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video_id")

    video = db.query(Video).filter(Video.id == vid).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    contents = await file.read()

    video_url = upload_to_storage(f"final/{video_id}.mp4", contents, "video/mp4")

    video.video_url = video_url
    video.status = "assembled"
    db.commit()
    db.refresh(video)

    return {
        "video_id": video_id,
        "video_path": video_url,
        "file_size_bytes": len(contents),
        "status": video.status,
    }
