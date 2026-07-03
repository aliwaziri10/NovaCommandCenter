import os
import re
import uuid
import requests
from sqlalchemy.orm import Session

from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip
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


def run_assembly(db, video_id):
    if isinstance(video_id, str):
        video_id = uuid.UUID(video_id)

    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise ValueError("Video not found")
    if not video.asset_urls:
        raise ValueError("Video has no asset_urls")
    if not video.audio_path or not os.path.exists(video.audio_path):
        raise ValueError("Video has no valid audio_path")
    if not video.production_plan:
        raise ValueError("Video has no production_plan")

    durations = _parse_durations(video.production_plan)
    urls = video.asset_urls
    n = min(len(urls), len(durations))
    if n == 0:
        raise ValueError("No shots to assemble")
    urls = urls[:n]
    durations = durations[:n]

    work_dir = os.path.join(MEDIA_ROOT, str(video.id), "images")
    os.makedirs(work_dir, exist_ok=True)
    output_dir = os.path.join(MEDIA_ROOT, str(video.id), "output")
    os.makedirs(output_dir, exist_ok=True)
    final_path = os.path.join(output_dir, "final.mp4")

    clips = []
    skipped = []
    errors = []
    for i, (url, dur) in enumerate(zip(urls, durations)):
        img_path = os.path.join(work_dir, "shot_%03d.jpg" % i)
        if not os.path.exists(img_path):
            ok = _download_image(url, img_path)
            if not ok:
                skipped.append(i)
                errors.append("shot %d: download failed" % i)
                continue
        try:
            clip = _ken_burns_clip(img_path, dur)
            clips.append(clip)
        except Exception as e:
            skipped.append(i)
            errors.append("shot %d: %s: %s" % (i, type(e).__name__, str(e)[:150]))
            continue

    if not clips:
        raise ValueError("All shots failed. Errors: %s" % errors)

    final_video = concatenate_videoclips(clips, method="compose", padding=-CROSSFADE)
    audio_clip = AudioFileClip(video.audio
