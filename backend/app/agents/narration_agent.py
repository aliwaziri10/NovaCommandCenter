import os
import re
import uuid
import asyncio
from sqlalchemy.orm import Session
from app.models.video import Video
from app.models.script import Script

import edge_tts

MEDIA_ROOT = "/app/data/media"
VOICE = "en-US-GuyNeural"


def _clean_narration_text(script_content: str) -> str:
    text = re.sub(r'\[SCENE[^\]]*\]', '', script_content, flags=re.IGNORECASE)
    text = re.sub(r'\n{2,}', '\n', text).strip()
    return text


async def _generate_audio(text: str, output_path: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)


def run_narration(db: Session, video_id: str):
    if isinstance(video_id, str):
        video_id = uuid.UUID(video_id)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise ValueError(f"Video {video_id} not found")
    if not video.script_id:
        raise ValueError(f"Video {video_id} has no linked script")

    script = db.query(Script).filter(Script.id == video.script_id).first()
    if not script or not script.content:
        raise ValueError("Linked script has no content to narrate")

    narration_text = _clean_narration_text(script.content)
    if not narration_text:
        raise ValueError("Narration text was empty after cleaning script content")

    video_dir = os.path.join(MEDIA_ROOT, str(video.id), "audio")
    os.makedirs(video_dir, exist_ok=True)
    final_path = os.path.join(video_dir, "narration.mp3")

    try:
        asyncio.run(_generate_audio(narration_text, final_path))
    except Exception as e:
        raise ValueError(f"Narration generation failed: {type(e).__name__}: {str(e)[:200]}")

    if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
        raise ValueError("Narration file was not created or is empty")

    video.audio_path = final_path
    db.commit()
    db.refresh(video)

    return {
        "video_id": str(video.id),
        "audio_path": final_path,
        "file_size_bytes": os.path.getsize(final_path),
        "voice": VOICE,
    }
