import gc
import os
import re
import subprocess
import uuid
import requests
from sqlalchemy.orm import Session

from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

import imageio_ffmpeg
from moviepy.editor import ImageClip, concatenate_videoclips
from app.models.video import Video

MEDIA_ROOT = "/app/data/media"
DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)
BLOCK_SIZE = 2  # shots rendered together per block, keeps memory low on 512MB Railway free tier

FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)


def _parse_durations(production_plan):
    durations = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not SHOT_START.match(line):
            continue
        match = DURATION_PATTERN.search(line)
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
    target_w, target_h = RESOLUTION

    base_clip = ImageClip(image_path)
    src_w, src_h = base_clip.size

    scale = max(target_w / src_w, target_h / src_h)
    scale = scale * 1.15

    resized_w = int(src_w * scale)
    resized_h = int(src_h * scale)

    clip = base_clip.set_duration(duration)
    clip = clip.resize(newsize=(resized_w, resized_h))

    def zoom(t):
        return 1 + 0.03 * (t / duration)

    clip = clip.resize(zoom)
    clip = clip.set_position(("center", "center"))
    clip = clip.crop(
        x_center=import gc
import os
import re
import subprocess
import uuid
import requests
from sqlalchemy.orm import Session

from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

import imageio_ffmpeg
from moviepy.editor import ImageClip, concatenate_videoclips
from app.models.video import Video

MEDIA_ROOT = "/app/data/media"
DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)
BLOCK_SIZE = 2  # shots rendered together per block, keeps memory low on 512MB Railway free tier

FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)


def _parse_durations(production_plan):
    durations = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not SHOT_START.match(line):
            continue
        match = DURATION_PATTERN.search(line)
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
    target_w, target_h = RESOLUTION

    base_clip = ImageClip(image_path)
    src_w, src_h = base_clip.size

    scale = max(target_w / src_w, target_h / src_h)
    scale = scale * 1.15

    resized_w = int(src_w * scale)
    resized_h = int(src_h * scale)

    clip = base_clip.set_duration(duration)
    clip = clip.resize(newsize=(resized_w, resized_h))

    def zoom(t):
        return 1 + 0.03 * (t / duration)

    clip = clip.resize(zoom)
    clip = clip.set_position(("center", "center"))
    clip = clip.crop(
        x_center=resized_w / 2,
        y_center=resized_h / 2,
        width=target_w,
        height=target_h,
    )
    clip = clip.crossfadein(min(CROSSFADE, duration / 2))
    return clip


def _run_ffmpeg(args):
    result = subprocess.run(
        [FFMPEG_BINARY, "-y"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed: %s" % result.stdout.decode(errors="ignore")[-2000:])


def _render_block(shot_indices, urls, durations, work_dir, block_output_path):
    """Render one block of shots to its ownresized_w / 2,
        y_center=resized_h / 2,
        width=target_w,
        height=target_h,
    )
    clip = clip.crossfadein(min(CROSSFADE, duration / 2))
    return clip


def _run_ffmpeg(args):
    result = subprocess.run(
        [FFMPEG_BINARY, "-y"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed: %s" % result.stdout.decode(errors="ignore")[-2000:])


def _render_block(shot_indices, urls, durations, work_dir, block_output_path):
    """Render one block of shots to its own
