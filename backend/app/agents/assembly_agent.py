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
