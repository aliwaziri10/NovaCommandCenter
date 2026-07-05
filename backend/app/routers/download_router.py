import os
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import FileResponse

MEDIA_ROOT = "/app/data/media"
ASSEMBLY_SECRET = os.environ.get("ASSEMBLY_SECRET")

router = APIRouter(prefix="/download", tags=["download"])


def verify_assembly_secret(x_assembly_secret: str = Header(None)):
    if not ASSEMBLY_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured: ASSEMBLY_SECRET not set")
    if x_assembly_secret != ASSEMBLY_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Assembly-Secret header")


@router.get("/videos/{video_id}")
def download_video(video_id: str):
    final_path = os.path.join(MEDIA_ROOT, video_id, "output", "final.mp4")
    if not os.path.exists(final_path):
        raise HTTPException(status_code=404, detail="No assembled video found for this video_id")
    return FileResponse(
        final_path,
        media_type="video/mp4",
        filename="episode_%s.mp4" % video_id,
    )


@router.get("/narration/{video_id}")
def download_narration(video_id: str, x_assembly_secret: str = Header(None)):
    verify_assembly_secret(x_assembly_secret)

    audio_path = os.path.join(MEDIA_ROOT, video_id, "audio", "narration.mp3")
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="No narration audio found for this video_id")
    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename="narration_%s.mp3" % video_id,
    )
