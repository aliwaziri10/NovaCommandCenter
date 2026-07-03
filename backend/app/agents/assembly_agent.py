import os
import re
import uuid
import requests
from sqlalchemy.orm import Session

from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

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
        match =
