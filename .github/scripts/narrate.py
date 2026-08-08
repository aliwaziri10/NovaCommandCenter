import asyncio
import os
import re
import subprocess
import uuid
from sqlalchemy.orm import Session
from app.models.video import Video
from app.models.script import Script
import edge_tts
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

MEDIA_ROOT = "/app/data/media"

# EDGE TTS (reverted 2026-08-09, matching Marius): replaces Chatterbox TTS.
# Chatterbox was ported in 2026-08-03/04 but never confirmed safe - see
# brain/KNOWN_BUGS.md and brain/SESSION_LOG.md. It carried two confirmed
# problems: (1) it loaded a real neural model IN-PROCESS inside the FastAPI
# backend on Render's free tier, a standing OOM/crash risk that was never
# resolved, and (2) its first (and only) live run on 2026-08-08 produced
# ~4s of audio for a ~555s-planned script - a near-total synthesis failure
# caught via Supabase task history, not by any exception. Edge TTS is
# lighter weight (no in-process model, calls Microsoft's cloud TTS service)
# and is the same engine already confirmed reliable on Marius. No built-in
# rate/speed param is used here either; slowdown is applied once at the end
# via ffmpeg atempo, same pattern the old gTTS/Chatterbox code already used.
EDGE_TTS_VOICE = os.environ.get("EDGE_TTS_VOICE", "en-US-AriaNeural")
SLOWDOWN_FACTOR = "0.95"

PAUSE_SECONDS_MIN = 1.0
PAUSE_SECONDS_MAX = 2.0

# FIX (2026-08-04): narration_agent had NO defense of its own against bad
# script content reaching text-to-speech. script_writing_agent.py was patched
# on 2026-08-03 to reject code/markup/JSON before saving a Script row, but
# that only protects scripts generated AFTER that fix went live. Any Script
# row already sitting in the database from before the fix (or reaching this
# agent through any future code path that isn't script_writing_agent) had
# zero protection - narration_agent would TTS whatever was in script.content,
# no questions asked. This guard makes narration_agent defend itself instead
# of trusting upstream to have done it.
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


def _split_into_sentences(narration_text):
    raw_segments = re.split(r"(?<=[.!?])\s+", narration_text.strip())
    segments = [seg.strip() for seg in raw_segments if seg.strip()]
    return segments if segments else [narration_text.strip()]


async def _synthesize_sentence_edge(text, tmp_path):
    communicate = edge_tts.Communicate(text, voice=EDGE_TTS_VOICE)
    await communicate.save(tmp_path)


def _synthesize_with_pauses(narration_text, tmp_dir):
    segments = _split_into_sentences(narration_text)
    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(segments):
        tmp_path = os.path.join(tmp_dir, f"sent_{i}.mp3")
        asyncio.run(_synthesize_sentence_edge(segment, tmp_path))
        clip = AudioSegment.from_file(tmp_path)
        # DIAGNOSTIC (carried over from the Chatterbox near-empty-audio bug):
        # log each segment's real length so a future failure points at the
        # exact sentence(s) that came out wrong, not just the aggregate total.
        print(f"  segment ({len(segment)} chars): {len(clip) / 1000.0:.2f}s audio")
        combined += clip
        if i < len(segments) - 1:
            pause_len = PAUSE_SECONDS_MIN if i % 2 == 0 else PAUSE_SECONDS_MAX
            combined += AudioSegment.silent(duration=int(pause_len * 1000))
    return combined


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
    raw_path = os.path.join(video_dir, "narration_raw.wav")
    final_path = os.path.join(video_dir, "narration.mp3")

    try:
        combined_audio = _synthesize_with_pauses(narration_text, video_dir)
        combined_audio = pydub_normalize(combined_audio)
        combined_audio.export(raw_path, format="wav")
    except Exception as e:
        raise ValueError(f"Narration generation failed: {type(e).__name__}: {str(e)[:200]}")

    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        raise ValueError("Narration file was not created or is empty")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", raw_path,
                "-filter:a", f"atempo={SLOWDOWN_FACTOR}",
                final_path,
            ],
            check=True,
            capture_output=True,
        )
        os.remove(raw_path)
    except Exception:
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
        "engine": "EdgeTTS",
        "slowdown_factor": SLOWDOWN_FACTOR,
    }
