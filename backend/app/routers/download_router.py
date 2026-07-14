import os
import uuid
from fastapi import APIRouter, HTTPException, Header, Depends
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.video import Video

MEDIA_ROOT = "/app/data/media"
ASSEMBLY_SECRET = os.environ.get("ASSEMBLY_SECRET")

router = APIRouter(prefix="/download", tags=["download"])


def verify_assembly_secret(x_assembly_secret: str = Header(None)):
    if not ASSEMBLY_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured: ASSEMBLY_SECRET not set")
    if x_assembly_secret != ASSEMBLY_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Assembly-Secret header")


@router.get("/videos/{video_id}")
def download_video(video_id: str, db: Session = Depends(get_db)):
    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video_id")

    video = db.query(Video).filter(Video.id == vid).first()

    # Durable Supabase Storage URL - redirect so callers (youtube_upload.py)
    # get the file even if Railway itself has restarted since assembly.
    # requests.get() follows redirects by default, so no caller changes needed.
    if video and video.video_url:
        return RedirectResponse(url=video.video_url)

    # Fallback for videos assembled before this fix, whose file only ever
    # lived on Railway's local disk - likely already gone if Railway has
    # restarted since, but worth trying before giving up.
    final_path = os.path.join(MEDIA_ROOT, video_id, "output", "final.mp4")
    if not os.path.exists(final_path):
        raise HTTPException(status_code=404, detail="No assembled video found for this video_id")
    return FileResponse(
        final_path,
        media_type="video/mp4",
        filename="episode_%s.mp4" % video_id,
    )


@router.get("/narration/{video_id}")
def download_narration(video_id: str, x_assembly_secret: str = Header(None), db: Session = Depends(get_db)):
    verify_assembly_secret(x_assembly_secret)

    try:
        vid = uuid.UUID(video_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid video_id")

    video = db.query(Video).filter(Video.id == vid).first()

    if video and video.audio_path and video.audio_path.startswith("http"):
        return RedirectResponse(url=video.audio_path)

    audio_path = os.path.join(MEDIA_ROOT, video_id, "audio", "narration.mp3")
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="No narration audio found for this video_id")
    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename="narration_%s.mp3" % video_id,
    )
