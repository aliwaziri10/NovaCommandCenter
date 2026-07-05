import os
import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.video import Video

MEDIA_ROOT = "/app/data/media"
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

    audio_dir = os.path.join(MEDIA_ROOT, video_id, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    dest_path = os.path.join(audio_dir, "narration.mp3")

    contents = await file.read()
    with open(dest_path, "wb") as f:
        f.write(contents)

    video.audio_path = dest_path
    db.commit()
    db.refresh(video)

    return {
        "video_id": video_id,
        "audio_path": dest_path,
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

    output_dir = os.path.join(MEDIA_ROOT, video_id, "output")
    os.makedirs(output_dir, exist_ok=True)
    dest_path = os.path.join(output_dir, "final.mp4")

    contents = await file.read()
    with open(dest_path, "wb") as f:
        f.write(contents)

    video.status = "assembled"
    db.commit()
    db.refresh(video)

    return {
        "video_id": video_id,
        "video_path": dest_path,
        "file_size_bytes": len(contents),
        "status": video.status,
    }
