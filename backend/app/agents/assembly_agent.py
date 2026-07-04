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
BLOCK_SIZE = 5  # shots rendered together per block, keeps memory low on 512MB Railway free tier

FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

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
    """Render one block of shots to its own small MP4 (no audio), then free memory."""
    clips = []
    skipped = []
    errors = []

    for i in shot_indices:
        url = urls[i]
        dur = durations[i]
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
        return skipped, errors, False

    block_video = concatenate_videoclips(clips, method="compose", padding=-CROSSFADE)
    block_video.write_videofile(
        block_output_path,
        fps=24,
        codec="libx264",
        audio=False,
        threads=2,
        preset="medium",
        verbose=False,
        logger=None,
    )

    # Explicitly release memory before moving to the next block
    block_video.close()
    for clip in clips:
        clip.close()
    del clips
    del block_video
    gc.collect()

    return skipped, errors, True


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
    blocks_dir = os.path.join(output_dir, "blocks")
    os.makedirs(blocks_dir, exist_ok=True)

    silent_path = os.path.join(output_dir, "silent_final.mp4")
    final_path = os.path.join(output_dir, "final.mp4")
    concat_list_path = os.path.join(output_dir, "concat_list.txt")

    all_skipped = []
    all_errors = []
    block_paths = []

    shot_indices = list(range(n))
    for block_start in range(0, n, BLOCK_SIZE):
        block_indices = shot_indices[block_start: block_start + BLOCK_SIZE]
        block_num = block_start // BLOCK_SIZE
        block_output_path = os.path.join(blocks_dir, "block_%03d.mp4" % block_num)

        skipped, errors, produced = _render_block(
            block_indices, urls, durations, work_dir, block_output_path
        )
        all_skipped.extend(skipped)
        all_errors.extend(errors)
        if produced:
            block_paths.append(block_output_path)

    if not block_paths:
        raise ValueError("All shots failed. Errors: %s" % all_errors)

    # Stitch the small block videos together (stream copy — very low memory)
    with open(concat_list_path, "w") as f:
        for p in block_paths:
            f.write("file '%s'\n" % p.replace("'", "'\\''"))

    _run_ffmpeg([
        "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        silent_path,
    ])

    # Mux the narration audio onto the stitched video (video stream copied, only audio re-encoded)
    _run_ffmpeg([
        "-i", silent_path,
        "-i", video.audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        final_path,
    ])

    video.status = "assembled"
    db.commit()
    db.refresh(video)

    return {
        "video_id": str(video.id),
        "output_path": final_path,
        "shots_used": n - len(all_skipped),
        "shots_skipped": all_skipped,
        "skip_errors": all_errors,
        "blocks_rendered": len(block_paths),
        "file_size_bytes": os.path.getsize(final_path) if os.path.exists(final_path) else 0,
    }
