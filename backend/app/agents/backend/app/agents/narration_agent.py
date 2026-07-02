import os
import re
import uuid
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models.video import Video
from app.models.script import Script

MEDIA_ROOT = "/app/data/media"


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

    max_chunk_chars = 500
    chunks = [narration_text[i:i + max_chunk_chars] for i in range(0, len(narration_text), max_chunk_chars)]

    video_dir = os.path.join(MEDIA_ROOT, str(video.id), "audio")
    os.makedirs(video_dir, exist_ok=True)

    chunk_paths = []
    failures = []
    for idx, chunk in enumerate(chunks):
        url = f"https://text.pollinations.ai/{quote(chunk)}"
        params = {"model": "openai-audio", "voice": "onyx"}
        try:
            response = requests.get(url, params=params, timeout=90)
            if response.status_code == 200 and response.content:
                chunk_path = os.path.join(video_dir, f"part_{idx:03d}.mp3")
                with open(chunk_path, "wb") as f:
                    f.write(response.content)
                chunk_paths.append(chunk_path)
            else:
                failures.append(f"chunk {idx}: HTTP {response.status_code}")
        except requests.RequestException as e:
            failures.append(f"chunk {idx}: {type(e).__name__}: {str(e)[:100]}")

    if not chunk_paths:
        raise ValueError(f"Narration generation failed for all chunks: {failures}")

    final_path = os.path.join(video_dir, "narration.mp3")
    with open(final_path, "wb") as outfile:
        for part in chunk_paths:
            with open(part, "rb") as infile:
                outfile.write(infile.read())

    video.audio_path = final_path
    db.commit()
    db.refresh(video)

    return {
        "video_id": str(video.id),
        "chunks_generated": len(chunk_paths),
        "chunks_failed": len(failures),
        "failure_reasons": failures,
        "audio_path": final_path,
    }
