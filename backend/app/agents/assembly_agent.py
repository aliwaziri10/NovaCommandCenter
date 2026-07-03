import os
import re
import uuid
import requests
from sqlalchemy.orm import Session
from PIL import Image

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, vfx
from app.models.video import Video

MEDIA_ROOT = "/app/data/media"
DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)

SHOT_LINE_PATTERN = re.compile(r"Shot\s+[\d.]+:.*?Duration:\s*([\d.]+)s", re.IGNORECASE)


def _parse_durations(production_plan):
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


def _download_image(url, dest_path):
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200 and len(resp.content) > 0:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return True
    except requests.RequestException:
        pass
    return False


def _ken_burns_clip(image_path, duration):
    clip = ImageClip(image_path)
    img_w, img_h = clip.size
    target_w, target_h = RESOLUTION

    # Scale proportionally so the image fully covers the frame (no stretching)
    scale = max(target_w / img_w, target_h / img_h)
    new_w, new_h = int(img_w * scale) + 2, int(img_h * scale) + 2
    clip = clip.resize((new_w, new_h))

    # Crop the overflow evenly from the centre
    clip = clip.fx(vfx.crop, x_center=new_w / 2, y_center=new_h / 2, width=target_w, height=target_h)
    clip = clip.set_duration(duration)

    # Slow zoom-in (Ken Burns), a bit more visible than before
    zoomed = clip.fx(vfx.resize, lambda t: 1 + 0.08 * (t / duration))
    zoomed = zoomed.set_position(("center", "center"))
    return zoomed.set_duration(duration)


def run_assembly(db: Session, video_id: str):
    if isinstance(video_id, str):
        video_id = uuid.UUID(video_id)

    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise ValueError(f"Video {video_id} not found")
    if not video.asset_urls:
        raise ValueError(f"Video {video_id} has no generated images (asset_urls empty)")
    if not video.audio_path or not os.path.exists(video.audio_path):
        raise ValueError(f"Video {video_id} has no narration audio available")

    video_dir = os.path.join(MEDIA_ROOT, str(video.id))
    images_dir = os.path.join(video_dir, "images")
    output_dir = os.path.join(video_dir, "output")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    durations = _parse_durations(video.production_plan or "")
    image_urls = video.asset_urls

    if len(durations) < len(image_urls):
        durations += [DEFAULT_SHOT_DURATION] * (len(image_urls) - len(durations))
    durations = durations[:len(image_urls)]

    local_paths = []
    failures = []
    for idx, url in enumerate(image_urls):
        dest = os.path.join(images_dir, f"shot_{idx:03d}.jpg")
        if os.path.exists(dest):
            local_paths.append(dest)
            continue
        if _download_image(url, dest):
            local_paths.append(dest)
        else:
            failures.append(f"shot {idx}: download failed")

    if not local_paths:
        raise ValueError(f"No images could be downloaded: {failures}")

    clips = []
    for path, duration in zip(local_paths, durations):
        try:
            clips.append(_ken_burns_clip(path, duration))
        except Exception as e:
            failures.append(f"{path}: clip build failed ({type(e).__name__})")

    if not clips:
        raise ValueError(f"No video clips could be built: {failures}")

    video_track = concatenate_videoclips(clips, method="compose", padding=-CROSSFADE)
    audio_track = AudioFileClip(video.audio_path)

    if video_track.duration < audio_track.duration:
        video_track = video_track.set_duration(audio_track.duration)
    else:
        video_track = video_track.subclip(0, audio_track.duration)

    final = video_track.set_audio(audio_track)

    output_path = os.path.join(output_dir, "final.mp4")
    final.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=2,
        preset="ultrafast",
    )

    video.status = "assembled"
    db.commit()
    db.refresh(video)

    return {
        "video_id": str(video.id),
        "output_path": output_path,
        "images_used": len(local_paths),
        "failures": failures,
        "duration_seconds": audio_track.duration,
    }
