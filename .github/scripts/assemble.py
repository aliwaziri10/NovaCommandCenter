import gc
import os
import re
import subprocess
import sys
import requests

from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

import imageio_ffmpeg
from moviepy.editor import ImageClip, VideoFileClip, concatenate_videoclips

RAILWAY_URL = os.environ["RAILWAY_URL"]
ASSEMBLY_SECRET = os.environ["ASSEMBLY_SECRET"]
VIDEO_ID = os.environ["VIDEO_ID"]

DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)
BLOCK_SIZE = 10

WORK_DIR = "/tmp/nova_assembly"
FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)

HEADERS = {"X-Assembly-Secret": ASSEMBLY_SECRET}


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


def _download_file(url, dest_path):
    try:
        resp = requests.get(url, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 0:
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return True
    except requests.RequestException:
        pass
    return False


def _still_image_clip(image_path, duration):
    target_w, target_h = RESOLUTION
    base_clip = ImageClip(image_path)
    src_w, src_h = base_clip.size

    scale = max(target_w / src_w, target_h / src_h)
    resized_w = int(src_w * scale)
    resized_h = int(src_h * scale)

    clip = base_clip.set_duration(duration)
    clip = clip.resize(newsize=(resized_w, resized_h))
    clip = clip.set_position(("center", "center"))
    clip = clip.crop(x_center=resized_w / 2, y_center=resized_h / 2, width=target_w, height=target_h)
    clip = clip.crossfadein(min(CROSSFADE, duration / 2))
    return clip


def _video_clip(video_path, duration):
    target_w, target_h = RESOLUTION
    base_clip = VideoFileClip(video_path)
    src_w, src_h = base_clip.size

    scale = max(target_w / src_w, target_h / src_h)
    resized_w = int(src_w * scale)
    resized_h = int(src_h * scale)

    clip = base_clip.resize(newsize=(resized_w, resized_h))
    clip = clip.set_position(("center", "center"))
    clip = clip.crop(x_center=resized_w / 2, y_center=resized_h / 2, width=target_w, height=target_h)

    if clip.duration >= duration:
        clip = clip.subclip(0, duration)
    else:
        clip = clip.set_duration(clip.duration)

    clip = clip.crossfadein(min(CROSSFADE, clip.duration / 2))
    return clip


def _run_ffmpeg(args):
    full_args = [FFMPEG_BINARY, "-y"] + args
    result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        error_text = result.stdout.decode(errors="ignore")[-2000:]
        raise RuntimeError("ffmpeg failed: " + error_text)


def _render_block(shot_indices, urls, durations, media_dir, block_output_path, use_clips):
    clips = []
    skipped = []
    errors = []

    for i in shot_indices:
        url = urls[i]
        dur = durations[i]
        ext = "mp4" if use_clips else "jpg"
        media_path = os.path.join(media_dir, "shot_%03d.%s" % (i, ext))
        if not os.path.exists(media_path):
            ok = _download_file(url, media_path)
            if not ok:
                skipped.append(i)
                errors.append("shot " + str(i) + ": download failed")
                continue
        try:
            if use_clips:
                clip = _video_clip(media_path, dur)
            else:
                clip = _still_image_clip(media_path, dur)
            clips.append(clip)
        except Exception as e:
            skipped.append(i)
            errors.append("shot " + str(i) + ": " + type(e).__name__ + ": " + str(e)[:150])
            continue

    if not clips:
        return skipped, errors, False

    block_video = concatenate_videoclips(clips, method="compose", padding=-CROSSFADE)
    block_video.write_videofile(
        block_output_path,
        fps=24,
        codec="libx264",
        audio=False,
        threads=4,
        preset="medium",
        verbose=False,
        logger=None,
    )

    block_video.close()
    for clip in clips:
        clip.close()
    del clips
    del block_video
    gc.collect()

    return skipped, errors, True


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    media_dir = os.path.join(WORK_DIR, "media")
    blocks_dir = os.path.join(WORK_DIR, "blocks")
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(blocks_dir, exist_ok=True)

    print("Fetching video data from Railway...")
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos/{VIDEO_ID}", timeout=30)
    resp.raise_for_status()
    video = resp.json()

    clip_urls = video.get("clip_urls")
    asset_urls = video.get("asset_urls")
    production_plan = video.get("production_plan")

    if clip_urls:
        print(f"Found {len(clip_urls)} video clips — using real video clips for assembly.")
        use_clips = True
        urls = clip_urls
    elif asset_urls:
        print(f"No video clips found. Falling back to {len(asset_urls)} still images.")
        use_clips = False
        urls = asset_urls
    else:
        print("ERROR: video has no clip_urls and no asset_urls")
        sys.exit(1)

    if not production_plan:
        print("ERROR: video has no production_plan")
        sys.exit(1)

    print("Downloading narration audio from Railway...")
    audio_path = os.path.join(WORK_DIR, "narration.mp3")
    audio_resp = requests.get(
        f"{RAILWAY_URL}/api/v1/download/narration/{VIDEO_ID}",
        headers=HEADERS,
        timeout=60,
    )
    audio_resp.raise_for_status()
    with open(audio_path, "wb") as f:
        f.write(audio_resp.content)

    durations = _parse_durations(production_plan)
    n = min(len(urls), len(durations))
    if n == 0:
        print("ERROR: no shots to assemble")
        sys.exit(1)
    urls = urls[:n]
    durations = durations[:n]

    silent_path = os.path.join(WORK_DIR, "silent_final.mp4")
    final_path = os.path.join(WORK_DIR, "final.mp4")
    concat_list_path = os.path.join(WORK_DIR, "concat_list.txt")

    all_skipped = []
    all_errors = []
    block_paths = []

    shot_indices = list(range(n))
    for block_start in range(0, n, BLOCK_SIZE):
        block_indices = shot_indices[block_start: block_start + BLOCK_SIZE]
        block_num = block_start // BLOCK_SIZE
        block_output_path = os.path.join(blocks_dir, "block_%03d.mp4" % block_num)

        print(f"Rendering block {block_num} (shots {block_indices})...")
        skipped, errors, produced = _render_block(block_indices, urls, durations, media_dir, block_output_path, use_clips)
        all_skipped.extend(skipped)
        all_errors.extend(errors)
        if produced:
            block_paths.append(block_output_path)

    if not block_paths:
        print("ERROR: all shots failed: " + str(all_errors))
        sys.exit(1)

    with open(concat_list_path, "w") as f:
        for p in block_paths:
            safe_p = p.replace("'", "'\\''")
            f.write("file '" + safe_p + "'\n")

    print("Concatenating
