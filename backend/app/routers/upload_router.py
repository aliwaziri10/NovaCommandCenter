import os
import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.video import Video

MEDIA_ROOT = "/app/data/media"

router = APIRouter(prefix="/upload", tags=["upload"])


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
