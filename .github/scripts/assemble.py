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
from moviepy.editor import ImageClip, concatenate_videoclips

RAILWAY_URL = os.environ["RAILWAY_URL"]
ASSEMBLY_SECRET = os.environ["ASSEMBLY_SECRET"]
VIDEO_ID = os.environ["VIDEO_ID"]

DEFAULT_SHOT_DURATION = 4.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)
BLOCK_SIZE = 10

WORK_DIR = "/tmp/nova_assembly"
FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SCENE_START = re.compile(r"^\*\*Scene\s*[\d.]+.*?[\u2013\-]\s*(\d+)\s*s\*\*", re.IGNORECASE)
SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**\s*:", re.IGNORECASE)

HEADERS = {"X-Assembly-Secret": ASSEMBLY_SECRET}


def _parse_durations(production_plan):
    """New format: duration is given once per SCENE (e.g. '**Scene 1 ... - 45 s**'),
    not once per shot. This splits that scene duration evenly across the shots
    listed under that scene."""
    durations = []
    current_scene_seconds = None
    current_scene_shot_lines = []

    def _flush():
        if not current_scene_shot_lines:
            return
        total = current_scene_seconds if current_scene_seconds else DEFAULT_SHOT_DURATION * len(current_scene_shot_lines)
        per_shot = total / len(current_scene_shot_lines)
        durations.extend([per_shot] * len(current_scene_shot_lines))

    for raw_line in production_plan.splitlines():
        line = raw_line.strip()
        scene_match = SCENE_START.match(line)
        if scene_match:
            _flush()
            current_scene_seconds = float(scene_match.group(1))
            current_scene_shot_lines = []
            continue
        if SHOT_START.match(line):
            current_scene_shot_lines.append(line)

    _flush()
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


def _static_clip(image_path, duration):
    """No zoom, no animated motion. Crop to fill the frame exactly, hold still,
    only the crossfade transition remains."""
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


def _run_ffmpeg(args):
    full_args = [FFMPEG_BINARY, "-y"] + args
    result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        error_text = result.stdout.decode(errors="ignore")[-2000:]
        raise RuntimeError("ffmpeg failed: " + error_text)


def _render_block(shot_indices, urls, durations, images_dir, block_output_path):
    clips = []
    skipped = []
    errors = []

    for i in shot_indices:
        url = urls[i]
        dur = durations[i]
        img_path = os.path.join(images_dir, "shot_%03d.jpg" % i)
        if not os.path.exists(img_path):
            ok = _download_image(url, img_path)
            if not ok:
                skipped.append(i)
                errors.append("shot " + str(i) + ": download failed")
                continue
        try:
            clip = _static_clip(img_path, dur)
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
    images_dir = os.path.join(WORK_DIR, "images")
    blocks_dir = os.path.join(WORK_DIR, "blocks")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(blocks_dir, exist_ok=True)

    print("Fetching video data from Railway...")
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos/{VIDEO_ID}", timeout=30)
    resp.raise_for_status()
    video = resp.json()

    asset_urls = video.get("asset_urls")
    production_plan = video.get("production_plan")
    if not asset_urls:
        print("ERROR: video has no asset_urls")
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
    n = min(len(asset_urls), len(durations))
    if n == 0:
        print("ERROR: no shots to assemble")
        sys.exit(1)
    urls = asset_urls[:n]
    durations = durations[:n]
    print(f"Matched {n} shots to durations. Total runtime: {sum(durations):.1f}s")

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
        skipped, errors, produced = _render_block(block_indices, urls, durations, images_dir, block_output_path)
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

    print("Concatenating blocks...")
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", silent_path])

    print("Merging narration audio...")
    _run_ffmpeg([
        "-i", silent_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        final_path,
    ])

    print("Uploading finished video back to Railway...")
    with open(final_path, "rb") as f:
        upload_resp = requests.post(
            f"{RAILWAY_URL}/api/v1/upload/video/{VIDEO_ID}",
            headers=HEADERS,
            files={"file": ("final.mp4", f, "video/mp4")},
            timeout=300,
        )
    upload_resp.raise_for_status()

    print("SUCCESS:", upload_resp.json())
    if all_skipped:
        print("Note: some shots were skipped:", all_errors)


if __name__ == "__main__":
    main()
