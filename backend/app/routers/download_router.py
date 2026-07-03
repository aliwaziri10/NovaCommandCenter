import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

MEDIA_ROOT = "/app/data/media"

router = APIRouter(prefix="/download", tags=["download"])


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
