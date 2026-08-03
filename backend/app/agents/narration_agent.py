import os
import re
import subprocess
import uuid
from sqlalchemy.orm import Session
from app.models.video import Video
from app.models.script import Script
from gtts import gTTS

MEDIA_ROOT = "/app/data/media"
NARRATION_SPEED = 0.9

# FIX (2026-08-04): narration_agent had NO defense of its own against bad
# script content reaching text-to-speech. script_writing_agent.py was patched
# on 2026-08-03 to reject code/markup/JSON before saving a Script row, but
# that only protects scripts generated AFTER that fix went live. Any Script
# row already sitting in the database from before the fix (or reaching this
# agent through any future code path that isn't script_writing_agent) had
# zero protection - narration_agent would TTS whatever was in script.content,
# no questions asked. This is exactly how a video ended up narrating raw
# Python source. This guard makes narration_agent defend itself instead of
# trusting upstream to have done it, so this failure mode can't recur even
# if a future change to script_writing_agent (or a new code path) reopens
# the same hole.
_CODE_LIKE_MARKERS = (
    "<html", "<!doctype", "<div", "<span", "<body", "<script",
    "```", "function(", "function (", "=>", "SELECT *", "import ",
    "def ", "class ", "{\"", "[{", "</",
)


def _looks_like_code_or_markup(text: str) -> bool:
    lowered = text.lower()
    hits = sum(1 for marker in _CODE_LIKE_MARKERS if marker.lower() in lowered)
    if hits >= 2:
        return True
    symbol_count = sum(text.count(ch) for ch in "{}<>[]")
    if symbol_count > 5 and (symbol_count / max(len(text), 1)) > 0.01:
        return True
    return False


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

    if _looks_like_code_or_markup(script.content):
        raise ValueError(
            f"Script {script.id} for video {video_id} looks like code/markup, "
            f"not narration text - refusing to narrate it. This script needs to "
            f"be regenerated (delete this Script row and re-run script_writing), "
            f"not narrated as-is."
        )

    narration_text = _clean_narration_text(script.content)
    if not narration_text:
        raise ValueError("Narration text was empty after cleaning script content")

    if _looks_like_code_or_markup(narration_text):
        raise ValueError(
            f"Script {script.id} for video {video_id} looks like code/markup "
            f"after cleaning - refusing to narrate it."
        )

    video_dir = os.path.join(MEDIA_ROOT, str(video.id), "audio")
    os.makedirs(video_dir, exist_ok=True)
    raw_path = os.path.join(video_dir, "narration_raw.mp3")
    final_path = os.path.join(video_dir, "narration.mp3")
    try:
        tts = gTTS(text=narration_text, lang="en", slow=False)
        tts.save(raw_path)
    except Exception as e:
        raise ValueError(f"Narration generation failed: {type(e).__name__}: {str(e)[:200]}")
    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        raise ValueError("Narration file was not created or is empty")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", raw_path,
                "-filter:a", f"atempo={NARRATION_SPEED}",
                final_path,
            ],
            check=True,
            capture_output=True,
        )
        os.remove(raw_path)
    except Exception as e:
        os.rename(raw_path, final_path)
    if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
        raise ValueError("Narration file was not created or is empty after speed adjustment")
    video.audio_path = final_path
    db.commit()
    db.refresh(video)
    return {
        "video_id": str(video.id),
        "audio_path": final_path,
        "file_size_bytes": os.path.getsize(final_path),
        "engine": "gTTS",
        "speed": NARRATION_SPEED,
    }
