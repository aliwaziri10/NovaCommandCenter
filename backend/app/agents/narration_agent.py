import os
import re
import uuid
import numpy as np
import soundfile as sf
from sqlalchemy.orm import Session
from app.models.video import Video
from app.models.script import Script
from kokoro import KPipeline

MEDIA_ROOT = "/app/data/media"

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = KPipeline(lang_code="a")
    return _pipeline


def _clean_narration_text(script_content: str) -> str:
    text = re.sub(r'\[SCENE[^\]]*\]', '', script_content, flags=re.IGNORECASE)
    text = re.sub(r'\n{2,}', '\n', text).strip()
    return text


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
    final_path = os.path.join(video_dir, "narration.wav")

    try:
        pipeline = _get_pipeline()
        generator = pipeline(narration_text, voice="am_adam", speed=1.0)
        audio_chunks = [audio for _, _, audio in generator]
        if not audio_chunks:
            raise ValueError("Kokoro produced no audio output")
        full_audio = np.concatenate(audio_chunks)
        sf.write(final_path, full_audio, 24000)
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
        "engine": "Kokoro (am_adam)",
    }
