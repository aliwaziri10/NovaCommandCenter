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
    try:
        audio_url = upload_to_storage(f"narration/{video_id}.mp3", contents, "audio/mpeg")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Supabase Storage upload failed: {e}")

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

    try:
        video_url = upload_to_storage(f"final/{video_id}.mp4", contents, "video/mp4")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Supabase Storage upload failed: {e}")

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


# ADDED (2026-08-03): supports continuity anchoring in generate_videos.py -
# stores an extracted last-frame PNG (used as the next shot's image-to-video
# anchor) in the same durable Supabase Storage used by narration/final video.
# `tag` is caller-defined (e.g. "{video_id}_shot003" or "{video_id}_resume")
# purely for a readable storage path - this endpoint doesn't touch the videos
# table at all, it just stores a file and hands back a public URL.
@router.post("/reference/{tag}")
async def upload_reference_frame(tag: str, file: UploadFile = File(...)):
    contents = await file.read()
    try:
        image_url = upload_to_storage(f"reference/{tag}.png", contents, "image/png")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Supabase Storage upload failed: {e}")
    return {
        "tag": tag,
        "url": image_url,
        "file_size_bytes": len(contents),
    }


# ADDED (2026-08-20): FREEZE-FRAME FIX support. generate_videos.py's
# chain-extension mechanism generates a shot as multiple real Agnes
# segments (for shots whose target duration exceeds the ~10s single-call
# ceiling), stitches them locally into one continuous clip, and needs
# somewhere durable to store that stitched result before handing its URL
# back to clip_urls - same durability reasoning as /video/{video_id}
# (Render's local disk is wiped on restart). No assembly secret required,
# matching the existing /reference/{tag} endpoint's permissiveness - this
# endpoint doesn't touch the videos table either, purely stores a file and
# returns a public URL for the caller to save into clip_urls itself.
@router.post("/clip/{tag}")
async def upload_clip(tag: str, file: UploadFile = File(...)):
    contents = await file.read()
    try:
        clip_url = upload_to_storage(f"clips/{tag}.mp4", contents, "video/mp4")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Supabase Storage upload failed: {e}")
    return {
        "tag": tag,
        "url": clip_url,
        "file_size_bytes": len(contents),
    }
