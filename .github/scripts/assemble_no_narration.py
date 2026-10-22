"""assemble_no_narration.py  (created 2026-10-22)

WHY THIS FILE EXISTS
  Zia asked for a version of a video with NO narration, only the SFX / clip
  audio / music, built from every clip that already exists even when some
  shots are still missing (assemble.py refuses to run unless all shots have
  clips, and always builds the soundtrack around narration).

  Evidence (assemble.py, main()): it exits with "NOT READY" unless every shot
  has a clip_url, and it downloads narration from
  /api/v1/download/narration/<id> and sizes the whole mix to it.

WHAT IT DOES DIFFERENTLY FROM assemble.py
  1. Requires VIDEO_ID (never auto-selects, so it cannot touch other videos).
  2. Uses only shots that have a clip_url; missing shots are skipped.
  3. No narration is downloaded or mixed.
  4. Soundtrack = native clip audio + per-shot Freesound SFX + chapter music.
     SFX placement uses the REAL rendered start time of each shot (short
     clips shift the timeline, so planned durations alone would drift).
  5. Does NOT upload to the GitHub Release and does NOT PATCH the backend, so
     the video is NOT marked assembled and youtube_upload.py never sees it.
     The file is written to OUTPUT_DIR and the workflow publishes it as a
     downloadable run artifact.
"""

import gc
import hashlib
import os
import re
import subprocess
import sys
import time

import numpy as np
import requests

from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

import imageio_ffmpeg
from moviepy.editor import (
    VideoFileClip,
    concatenate_videoclips,
    AudioFileClip,
    CompositeAudioClip,
    concatenate_audioclips,
)

RAILWAY_URL = os.environ.get("RAILWAY_URL", "https://novacommandcenter.onrender.com")
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/tmp/nova_no_narration_out")

FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "").strip()
FREESOUND_ENABLED = bool(FREESOUND_API_KEY)
FREESOUND_SEARCH_URL = "https://freesound.org/apiv2/search/text/"
SFX_MAX_SEARCHES_PER_RUN = 90

# Levels are higher than assemble.py because there is no narration to sit
# under. assemble.py uses SFX 0.22 / native 0.16 / music 0.10.
SFX_VOLUME = 0.55
NATIVE_SFX_VOLUME = 0.45
MUSIC_ENABLED = True
MUSIC_VOLUME = 0.14
MUSIC_CROSSFADE = 2.0
MUSIC_BASE_URL = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
LIMITER_CEILING = 0.98

DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)
BLOCK_SIZE = 10

VIDEO_CRF = 26
AUDIO_BITRATE_KBPS = 128
OUTPUT_RESOLUTION_VF = "scale=1920:1080"
CINEMATIC_VF_BASE = (
    f"{OUTPUT_RESOLUTION_VF},"
    "eq=contrast=1.05:brightness=0.04:saturation=1.05,"
    "curves=preset=medium_contrast,"
    "colorbalance=rs=0.03:rh=0.02"
)
LOUDNORM_AF = "loudnorm=I=-16:LRA=11:TP=-1.5"

_MUSIC_CHAPTERS = [
    ("Cold Open", "tense_mysterious", "The-Cannery.mp3"),
    ("Problem/Stakes", "moody_dread", "Ossuary-6-Air.mp3"),
    ("Rising Delivery", "building_tension", "Long-Note-One.mp3"),
    ("Midpoint Twist", "dramatic_shift", "Rite-of-Passage.mp3"),
    ("Climax", "intense_epic", "Impact-Moderato.mp3"),
    ("Payoff", "resolving_uplifting", "Thoughtful.mp3"),
]

WORK_DIR = "/tmp/nova_assembly_no_narration"
FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SHOT_START = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)
FFMPEG_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
SFX_PATTERN = re.compile(r"SFX\*{0,2}\s*:\s*\*{0,2}\s*([^\n]+)", re.IGNORECASE)


def _resilient_get(url, max_attempts=5, **kwargs):
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, **kwargs)
            if resp.status_code in (502, 503, 504):
                raise requests.RequestException(
                    f"backend not ready yet (HTTP {resp.status_code})"
                )
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt == max_attempts:
                break
            wait = min(10 * attempt, 45)
            print(f"Backend not ready (attempt {attempt}/{max_attempts}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise last_exc


def _parse_shots_count(production_plan):
    count = 0
    for line in production_plan.splitlines():
        if SHOT_START.match(line.strip()):
            count += 1
    return count


def _parse_durations(production_plan):
    durations = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not SHOT_START.match(line):
            continue
        match = DURATION_PATTERN.search(line)
        durations.append(float(match.group(1)) if match else DEFAULT_SHOT_DURATION)
    return durations


def _parse_sfx_keywords(production_plan, total_shots):
    keywords = []
    current_keyword = None
    for line in production_plan.splitlines():
        stripped = line.strip()
        if SHOT_START.match(stripped):
            if current_keyword is not None or keywords:
                keywords.append(current_keyword)
            current_keyword = None
            continue
        match = SFX_PATTERN.search(stripped)
        if match and current_keyword is None:
            current_keyword = match.group(1).strip().strip("*").strip()
    keywords.append(current_keyword)
    keywords = keywords[1:] if keywords and keywords[0] is None and len(keywords) > total_shots else keywords
    while len(keywords) < total_shots:
        keywords.append(None)
    return keywords[:total_shots]


def _resolve_durations(video, production_plan, total_shots):
    real = video.get("shot_durations")
    if real and len(real) >= total_shots:
        print(f"Using real shot_durations ({len(real)} shots).")
        return [float(d) for d in real[:total_shots]]
    print("No complete shot_durations on this video - using planned durations parsed from the production plan.")
    plan = _parse_durations(production_plan)
    while len(plan) < total_shots:
        plan.append(DEFAULT_SHOT_DURATION)
    return plan


_sfx_cache = {}
_sfx_search_count = 0


def _fetch_shot_sfx(keyword, work_dir):
    global _sfx_search_count

    if not FREESOUND_ENABLED or not keyword:
        return None

    cache_key = keyword.lower().strip()
    if cache_key in _sfx_cache:
        return _sfx_cache[cache_key]

    if _sfx_search_count >= SFX_MAX_SEARCHES_PER_RUN:
        print(f"  [sfx] per-run search cap ({SFX_MAX_SEARCHES_PER_RUN}) reached - '{keyword}' gets no SFX.")
        _sfx_cache[cache_key] = None
        return None

    try:
        _sfx_search_count += 1
        resp = requests.get(
            FREESOUND_SEARCH_URL,
            params={
                "query": keyword,
                "token": FREESOUND_API_KEY,
                "fields": "id,name,previews,duration",
                "filter": "duration:[0.3 TO 15]",
                "sort": "score",
                "page_size": 1,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  [sfx] search failed for '{keyword}' (HTTP {resp.status_code}).")
            _sfx_cache[cache_key] = None
            return None

        results = resp.json().get("results") or []
        if not results:
            print(f"  [sfx] no Freesound results for '{keyword}'.")
            _sfx_cache[cache_key] = None
            return None

        preview_url = (results[0].get("previews") or {}).get("preview-hq-mp3")
        if not preview_url:
            print(f"  [sfx] result for '{keyword}' had no usable preview.")
            _sfx_cache[cache_key] = None
            return None

        safe_name = hashlib.md5(cache_key.encode()).hexdigest()[:12]
        dest_path = os.path.join(work_dir, f"sfx_{safe_name}.mp3")
        dl_resp = requests.get(preview_url, timeout=30)
        if dl_resp.status_code != 200 or len(dl_resp.content) == 0:
            print(f"  [sfx] preview download failed for '{keyword}'.")
            _sfx_cache[cache_key] = None
            return None

        with open(dest_path, "wb") as f:
            f.write(dl_resp.content)
        _sfx_cache[cache_key] = dest_path
        return dest_path
    except Exception as e:
        print(f"  [sfx] lookup failed for '{keyword}' ({type(e).__name__}: {e}).")
        _sfx_cache[cache_key] = None
        return None


def _compute_shot_starts(blocks):
    """blocks = list of blocks; each block is a list of (shot_index, shown_length)
    in render order. Mirrors concatenate_videoclips(padding=-CROSSFADE): inside
    a block each clip starts CROSSFADE before the previous one ends; blocks are
    joined back to back with no overlap. Returns ({shot_index: (start, length)},
    total_duration)."""
    placement = {}
    block_offset = 0.0
    for block in blocks:
        cursor = 0.0
        for j, (idx, length) in enumerate(block):
            start = block_offset + cursor
            placement[idx] = (start, length)
            cursor += length - CROSSFADE
        block_total = (cursor + CROSSFADE) if block else 0.0
        block_offset += block_total
    return placement, block_offset


def _build_sfx_bed(sfx_keywords, placement, total_duration, work_dir):
    if not FREESOUND_ENABLED:
        return None

    segments = []
    for idx in sorted(placement):
        keyword = sfx_keywords[idx] if idx < len(sfx_keywords) else None
        if not keyword:
            continue
        start, length = placement[idx]
        sfx_path = _fetch_shot_sfx(keyword, work_dir)
        if not sfx_path:
            continue
        try:
            clip = AudioFileClip(sfx_path).volumex(SFX_VOLUME)
            if clip.duration > length:
                clip = clip.subclip(0, length)
            segments.append(clip.set_start(start))
        except Exception as e:
            print(f"  [sfx] failed to load clip for shot {idx} ({type(e).__name__}: {e}).")

    if not segments:
        print("  [sfx] no usable SFX this run - proceeding without a Freesound SFX layer.")
        return None

    bed = CompositeAudioClip(segments).set_duration(total_duration)
    print(f"  [sfx] built SFX bed from {len(segments)}/{len(placement)} shots "
          f"({_sfx_search_count} Freesound searches).")
    return bed


def _download_file(url, dest_path, max_attempts=4):
    last_reason = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, timeout=120)
            if resp.status_code == 200 and len(resp.content) > 0:
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
                return True
            last_reason = f"HTTP {resp.status_code}, {len(resp.content)} bytes"
        except requests.RequestException as e:
            last_reason = str(e)
        if attempt == max_attempts:
            break
        wait = min(5 * attempt, 20)
        print(f"  [download] attempt {attempt}/{max_attempts} failed for {url}: {last_reason}. Retrying in {wait}s...")
        time.sleep(wait)
    print(f"  [download] GAVE UP after {max_attempts} attempts on {url}: {last_reason}")
    return False


def _fit_clip_to_duration(clip, target_duration, shot_index=None):
    # Same rule as assemble.py: short clips play at their real length, no freeze-frame.
    if clip.duration >= target_duration:
        return clip.subclip(0, target_duration)
    print(f"  [short-clip] shot {shot_index}: target={target_duration:.2f}s, actual={clip.duration:.2f}s.")
    return clip


def _video_clip(video_path, duration, shot_index=None):
    target_w, target_h = RESOLUTION
    base_clip = VideoFileClip(video_path)
    src_w, src_h = base_clip.size

    scale = max(target_w / src_w, target_h / src_h)
    resized_w = int(src_w * scale)
    resized_h = int(src_h * scale)

    clip = base_clip.resize(newsize=(resized_w, resized_h))
    clip = clip.set_position(("center", "center"))
    clip = clip.crop(x_center=resized_w / 2, y_center=resized_h / 2, width=target_w, height=target_h)
    clip = _fit_clip_to_duration(clip, duration, shot_index=shot_index)
    clip = clip.crossfadein(min(CROSSFADE, clip.duration / 2))
    return clip


def _run_ffmpeg(args, allow_fail=False):
    full_args = [FFMPEG_BINARY, "-y"] + args
    result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        error_text = result.stdout.decode(errors="ignore")[-2000:]
        if allow_fail:
            print("ffmpeg step failed (continuing without it): " + error_text)
            return False
        raise RuntimeError("ffmpeg failed: " + error_text)
    return True


def _render_block(shot_indices, urls, durations, media_dir, block_output_path):
    """Returns (skipped, errors, produced, shown) where shown is a list of
    (shot_index, shown_length) for every clip that made it into the block."""
    clips = []
    shown = []
    skipped = []
    errors = []
    last_index_in_block = shot_indices[-1] if shot_indices else None

    for i in shot_indices:
        dur = durations[i]
        effective_dur = dur if i == last_index_in_block else dur + CROSSFADE
        media_path = os.path.join(media_dir, "shot_%03d.mp4" % i)
        if not os.path.exists(media_path):
            if not _download_file(urls[i], media_path):
                skipped.append(i)
                errors.append("shot " + str(i) + ": download failed")
                continue
        try:
            clip = _video_clip(media_path, effective_dur, shot_index=i)
            clips.append(clip)
            shown.append((i, float(clip.duration)))
        except Exception as e:
            skipped.append(i)
            errors.append("shot " + str(i) + ": " + type(e).__name__ + ": " + str(e)[:150])

    if not clips:
        return skipped, errors, False, []

    block_video = concatenate_videoclips(clips, method="compose", padding=-CROSSFADE)
    block_video.write_videofile(
        block_output_path,
        fps=24,
        codec="libx264",
        audio=True,
        audio_codec="aac",
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
    return skipped, errors, True, shown


def _extract_native_audio(video_path, out_path):
    ok = _run_ffmpeg(
        ["-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", out_path],
        allow_fail=True,
    )
    if not ok or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        return None
    return out_path


def _get_video_duration(video_path):
    result = subprocess.run(
        [FFMPEG_BINARY, "-i", video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.decode(errors="ignore")
    match = FFMPEG_DURATION_PATTERN.search(output)
    if not match:
        raise RuntimeError("Could not read video duration from ffmpeg output:\n" + output[-1000:])
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _fit_audio_to_duration(audio_clip, target):
    if audio_clip.duration >= target:
        return audio_clip.subclip(0, target)
    reps = int(target // audio_clip.duration) + 1
    looped = concatenate_audioclips([audio_clip] * reps)
    return looped.subclip(0, target)


def _apply_safety_limiter(audio_clip, ceiling=LIMITER_CEILING):
    # Chunked peak scan (works on every numpy version; the whole-array
    # to_soundarray() call crashed in the 2026-10-22 sandbox test with newer numpy).
    peak = 0.0
    for chunk in audio_clip.iter_chunks(chunk_duration=5.0, fps=44100, quantize=False):
        if chunk.size:
            peak = max(peak, float(np.max(np.abs(chunk))))
    if peak <= 0 or peak <= ceiling:
        return audio_clip
    scale = ceiling / peak
    print(f"Safety limiter: peak {peak:.3f} exceeds {ceiling} - scaling mix by {scale:.3f}.")
    return audio_clip.volumex(scale)


def _chapter_time_bounds(total_duration):
    cold_open_end = min(30.0, total_duration)
    fraction_bounds = [
        (cold_open_end, 0.25 * total_duration),
        (0.25 * total_duration, 0.50 * total_duration),
        (0.50 * total_duration, 0.55 * total_duration),
        (0.55 * total_duration, 0.85 * total_duration),
        (0.85 * total_duration, total_duration),
    ]
    all_bounds = [(0.0, cold_open_end)] + fraction_bounds
    result = []
    for (start, end), (label, mood, filename) in zip(all_bounds, _MUSIC_CHAPTERS):
        if end > start:
            result.append((start, end, label, mood, filename))
    return result


def _build_music_bed(total_duration, work_dir):
    if not MUSIC_ENABLED:
        return None

    bounds = _chapter_time_bounds(total_duration)
    n = len(bounds)
    segments = []

    for idx, (start, end, label, mood, filename) in enumerate(bounds):
        pre = MUSIC_CROSSFADE / 2 if idx > 0 else 0.0
        post = MUSIC_CROSSFADE / 2 if idx < n - 1 else 0.0
        seg_start = max(start - pre, 0.0)
        seg_end = min(end + post, total_duration)
        seg_duration = seg_end - seg_start
        if seg_duration <= 0:
            continue

        track_path = os.path.join(work_dir, f"music_{filename}")
        if not os.path.exists(track_path):
            if not _download_file(MUSIC_BASE_URL + filename, track_path, max_attempts=2):
                print(f"  [music] '{label}' track failed to download - that segment is silent.")
                continue
        try:
            raw_clip = AudioFileClip(track_path)
            fitted = _fit_audio_to_duration(raw_clip, seg_duration).volumex(MUSIC_VOLUME)
            if pre > 0:
                fitted = fitted.audio_fadein(MUSIC_CROSSFADE)
            if post > 0:
                fitted = fitted.audio_fadeout(MUSIC_CROSSFADE)
            segments.append(fitted.set_start(seg_start))
        except Exception as e:
            print(f"  [music] '{label}' failed to load ({type(e).__name__}: {e}).")

    if not segments:
        print("  [music] no tracks available - proceeding without music.")
        return None

    bed = CompositeAudioClip(segments).set_duration(total_duration)
    print(f"  [music] built music bed from {len(segments)}/{n} chapter cues "
          f"(Kevin MacLeod, incompetech.com, CC BY 3.0 - credit him if you publish this).")
    return bed


def _build_mixed_audio(native_path, sfx_bed, music_bed, duration, out_path):
    layers = []
    if native_path:
        print("Mixing in native clip audio.")
        native = _fit_audio_to_duration(AudioFileClip(native_path), duration).volumex(NATIVE_SFX_VOLUME)
        layers.append(native)
    else:
        print("No native clip audio found.")
    if sfx_bed:
        print("Mixing in per-shot Freesound SFX.")
        layers.append(sfx_bed)
    if music_bed:
        print("Mixing in chapter music bed.")
        layers.append(music_bed)

    if not layers:
        return False

    mixed = CompositeAudioClip(layers).set_duration(duration)
    mixed = _apply_safety_limiter(mixed)
    mixed.write_audiofile(out_path, fps=44100, logger=None)
    for layer in layers:
        layer.close()
    mixed.close()
    return True


def main():
    if not VIDEO_ID:
        print("ERROR: VIDEO_ID is required. This script never auto-selects a video.")
        sys.exit(1)

    os.makedirs(WORK_DIR, exist_ok=True)
    media_dir = os.path.join(WORK_DIR, "media")
    blocks_dir = os.path.join(WORK_DIR, "blocks")
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(blocks_dir, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not FREESOUND_ENABLED:
        print("FREESOUND_API_KEY not set - the per-shot SFX layer will be skipped "
              "(native clip audio and music are unaffected).")

    print(f"Fetching video {VIDEO_ID} from the backend...")
    resp = _resilient_get(f"{RAILWAY_URL}/api/v1/videos/{VIDEO_ID}", timeout=90)
    resp.raise_for_status()
    video = resp.json()

    clip_urls = video.get("clip_urls") or []
    production_plan = video.get("production_plan")
    if not production_plan:
        print("ERROR: video has no production_plan")
        sys.exit(1)

    total_shots = _parse_shots_count(production_plan)
    if total_shots == 0:
        print("ERROR: no shots parsed from production_plan")
        sys.exit(1)

    durations = _resolve_durations(video, production_plan, total_shots)
    n = min(total_shots, len(durations))
    sfx_keywords = _parse_sfx_keywords(production_plan, total_shots)

    available = [i for i in range(n) if i < len(clip_urls) and clip_urls[i]]
    missing = [i for i in range(n) if i not in set(available)]
    print(f"Shots in plan: {n}. Clips available: {len(available)}. Missing (will be skipped): {len(missing)}.")
    if missing:
        print("Missing shot numbers (0-based): " + ", ".join(str(m) for m in missing))
    if not available:
        print("ERROR: this video has no clips at all - nothing to assemble.")
        sys.exit(1)

    silent_path = os.path.join(WORK_DIR, "silent_final.mp4")
    native_sfx_path = os.path.join(WORK_DIR, "native_sfx.wav")
    mixed_audio_path = os.path.join(WORK_DIR, "mixed_audio.wav")
    concat_list_path = os.path.join(WORK_DIR, "concat_list.txt")
    final_path = os.path.join(OUTPUT_DIR, f"{VIDEO_ID}_no_narration.mp4")

    all_errors = []
    block_paths = []
    block_shown = []

    for block_start in range(0, len(available), BLOCK_SIZE):
        block_indices = available[block_start: block_start + BLOCK_SIZE]
        block_num = block_start // BLOCK_SIZE
        block_output_path = os.path.join(blocks_dir, "block_%03d.mp4" % block_num)
        print(f"Rendering block {block_num} (shots {block_indices})...")
        skipped, errors, produced, shown = _render_block(
            block_indices, clip_urls, durations, media_dir, block_output_path
        )
        all_errors.extend(errors)
        if produced:
            block_paths.append(block_output_path)
            block_shown.append(shown)

    if not block_paths:
        print("ERROR: every shot failed to render: " + str(all_errors))
        sys.exit(1)

    with open(concat_list_path, "w") as f:
        for p in block_paths:
            f.write("file '" + p.replace("'", "'\\''") + "'\n")

    print("Joining video blocks...")
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", silent_path])

    video_duration = _get_video_duration(silent_path)
    placement, computed_total = _compute_shot_starts(block_shown)
    print(f"Video length: {video_duration:.1f}s (timeline estimate for SFX placement: {computed_total:.1f}s).")

    print("Extracting native clip audio...")
    extracted = _extract_native_audio(silent_path, native_sfx_path)

    print("Building music bed...")
    music_bed = None
    try:
        music_bed = _build_music_bed(video_duration, WORK_DIR)
    except Exception as e:
        print(f"  [music] failed entirely ({type(e).__name__}: {e}) - continuing without music.")

    print("Building per-shot SFX bed (Freesound)...")
    sfx_bed = None
    try:
        sfx_bed = _build_sfx_bed(sfx_keywords, placement, video_duration, media_dir)
    except Exception as e:
        print(f"  [sfx] failed entirely ({type(e).__name__}: {e}) - continuing without per-shot SFX.")

    has_audio = _build_mixed_audio(extracted, sfx_bed, music_bed, video_duration, mixed_audio_path)

    if has_audio:
        print("Applying cinematic grade and merging the soundtrack (no narration)...")
        _run_ffmpeg([
            "-i", silent_path,
            "-i", mixed_audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", CINEMATIC_VF_BASE,
            "-af", LOUDNORM_AF,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", str(VIDEO_CRF),
            "-c:a", "aac",
            "-b:a", f"{AUDIO_BITRATE_KBPS}k",
            "-shortest",
            final_path,
        ])
    else:
        print("WARNING: no audio layers were available at all - the output will be silent.")
        _run_ffmpeg([
            "-i", silent_path,
            "-vf", CINEMATIC_VF_BASE,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", str(VIDEO_CRF),
            "-an",
            final_path,
        ])

    size_mb = os.path.getsize(final_path) / (1024 * 1024)
    print(f"SUCCESS: wrote {final_path} ({size_mb:.1f}MB, {len(available)} of {n} shots, no narration).")
    if all_errors:
        print("Note: some shots had issues:", all_errors)
    print("The backend was NOT changed - this video is not marked assembled and will not be uploaded.")


if __name__ == "__main__":
    main()
