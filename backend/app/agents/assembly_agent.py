import os
import re
import uuid
import requests
from sqlalchemy.orm import Session
from moviepy.editor import (
    ImageClip,
    concatenate_videoclips,
    AudioFileClip,
)
from app.models.video import Video

MEDIA_ROOT = "/app/data/media"
DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)

SHOT_LINE_PATTERN = re.compile(
    r"Shot\s+[\d.]+:.*?Duration:\s*([\d.]+)s",
    re.IGNORECASE,
)


def _parse_durations(production_plan: str) -> list[float]:
    durations = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not line.lower().startswith("shot"):
            continue
        match = SHOT_LINE_PATTERN.search(line)
        if match:
            durations.append(float(match.group(1)))
        else:
            durations.append(DEFAULT_SHOT_DURATION)
    return durations


def _download_image(url: str, dest_path: str) -> bool:
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200 and len(resp.content) > 0:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return True
    except requests.RequestException:
        pass
    return False


def _ken_burns_clip(image_path: str, duration: float):
    clip = ImageClip(image_path).set_duration(duration)
    clip = clip.resize(height=RESOLUTION[1] + 200)
    w, h = clip.size
    if w < RESOLUTION[0]:
        clip = clip.resize(width=RESOLUTION[0] + 200)
        w, h = clip.size

    def zoom(t):
        return 1 + 0.03 * (t / duration)

    clip = clip.resize(zoom)
    clip = clip.set_position(("center", "center"))
    clip = clip.crossfadein(min(CROSSFADE, duration / 2))
    return clip


def run_assembly(db: Session, video_id):
    if isinstance(video_id, str):
        video_id = uuid.UUID(video_id)

    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise ValueError(f"Video {video_id} not found")
    if not video.asset_urls:
        raise ValueError("Video has no asset_urls (run asset_generation first)")
    if not video.audio_path or not os.path.exists(video.audio_path):
        raise ValueError("Video has no valid audio_path (run narration first)")
    if not video.production_plan:
        raise ValueError("Video has no production_plan")

    durations = _parse_durations(video.production_plan)
    urls = video.asset_urls

    n = min(len(urls), len(durations))
    if n == 0:
        raise ValueError("No shots to assemble (durations or asset_urls empty)")
    urls = urls[:n]
    durations = durations[:n]

    work_dir = os.path.join(MEDIA_ROOT, str(video.id), "images")
    os.makedirs(work_dir, exist_ok=True)
    output_dir = os.path.join(MEDIA_ROOT, str(video.id), "output")
    os.makedirs(output_dir, exist_ok=True)
    final_path = os.path.join(output_dir, "final.mp4")

    clips = []
    skipped = []
    for i, (url, dur) in enumerate(zip(urls, durations)):
        img_path = os.path.join(work_dir, f"shot_{i:03d}.jpg")
        if not os.path.exists(img_path):
            ok = _download_image(url, img_path)
            if not ok:
                skipped.append(i)
                continue
        try:
            clip = _ken_burns_clip(img_path, dur)
            clips.append(clip)
        except Exception:
            skipped.append(i)
            continue

    if not clips:
        raise ValueError("All shots failed to download or process — nothing to assemble")

    final_video = concatenate_videoclips(clips, method="compose", padding=-CROSSFADE)
    audio_clip = AudioFileClip(video.audio_path)
    final_video = final_video.set_audio(audio_clip)

    final_video.write_videofile(
        final_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=2,
        preset="medium",
        verbose=False,
        logger=None,
    )

    video.status = "assembled"
    db.commit()
    db.refresh(video)

    return {
        "video_id": str(video.id),
        "output_path": final_path,
        "shots_used": len(clips),
        "shots_skipped": skipped,
        "file_size_bytes": os.path.getsize(final_path) if os.path.exists(final_path) else 0,
    }
