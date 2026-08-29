import gc
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
    ImageClip,
    VideoFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
    AudioFileClip,
    CompositeAudioClip,
    concatenate_audioclips,
)

RAILWAY_URL = os.environ["RAILWAY_URL"]
ASSEMBLY_SECRET = os.environ["ASSEMBLY_SECRET"]
VIDEO_ID = os.environ.get("VIDEO_ID", "").strip()

DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)
BLOCK_SIZE = 10
KEN_BURNS_ZOOM = 0.08
# ADDED (2026-08-26): small fixed freeze-hold tacked onto the very end of
# the finished video (after narration ends), per Zia's request - without
# this, the video cuts the instant the last shot/narration finishes,
# which reads as an abrupt stop rather than a settled ending.
END_FREEZE_SECONDS = 0.75

# LOWERED (2026-08-29): was 45. Upload to Supabase Storage was failing
# (400, then surfaced as an unhandled 500 from the backend) because the
# actual rendered file size regularly overshoots this "budget" - ffmpeg's
# -b:v/-maxrate/-bufsize only bound the *average* bitrate, not the final
# file size, and confirmed live this was landing at 53.9MB against a
# 45MB budget. The Supabase bucket's file_size_limit has separately been
# raised (200MB) so overshoot alone won't block uploads going forward,
# but tightening this budget's margin keeps files smaller/faster to
# upload and stops the bitrate calc from being so close to any limit.
TARGET_UPLOAD_MB = 35
AUDIO_BITRATE_KBPS = 128
MIN_VIDEO_KBPS = 400
# RESOLUTION UPGRADE (2026-08-28): was "scale=1280:720" - this composite
# is already rendered/assembled at full 1920x1080 (see RESOLUTION above),
# but the final cinematic-grade ffmpeg pass was silently downscaling it
# back down to 720p on every single export for no technical reason. Fixed
# to match RESOLUTION so the 1080p Nova already renders internally is
# actually what reaches the uploaded file, instead of being thrown away.
OUTPUT_RESOLUTION_VF = "scale=1920:1080"

CINEMATIC_VF_BASE = (
    f"{OUTPUT_RESOLUTION_VF},"
    "eq=contrast=1.05:brightness=0.04:saturation=1.05,"
    "curves=preset=medium_contrast,"
    "colorbalance=rs=0.03:rh=0.02"
)
LOUDNORM_AF = "loudnorm=I=-16:LRA=11:TP=-1.5"

NATIVE_SFX_VOLUME = 0.16
NARRATION_VOLUME_WITH_LAYERS = 0.95
LIMITER_CEILING = 0.98

WORK_DIR = "/tmp/nova_assembly"
FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SHOT_START = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)
FFMPEG_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")

HEADERS = {"X-Assembly-Secret": ASSEMBLY_SECRET}

# DIAGNOSTIC (2026-08-16): accumulates every shot's (target, actual, pad)
# across the whole run so we can print a summary at the end confirming or
# ruling out "Agnes systematically returns clips shorter than requested"
# the cause of near-universal freeze-hold padding at scene ends.
_FREEZE_PAD_LOG = []


def _resilient_get(url, max_attempts=5, **kwargs):
    """COLD-START FIX (2026-08-21): Render's free-tier backend spins down
    after ~15 min idle and cold-starts on the next request. This script
    runs on a GitHub Actions cron, so its very first request to the
    backend can land during that cold-start window and get a connection
    error or a 502/503 from Render's edge before the app is ready. With
    no retry, that killed the ENTIRE run before any real work started -
    confirmed live: assemble workflow run #301 failed within seconds of
    the backend container even finishing its boot
    (2026-08-21T02:54:41Z fail vs 02:54:49-02:55:07Z container startup
    in Render's own logs). Retrying with backoff means a cold start no
    longer aborts the whole job.
    """
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


def _resilient_post(url, max_attempts=5, **kwargs):
    """UPLOAD COLD-START FIX (2026-08-22): confirmed live on run #309 -
    the upload POST at the very end of main() (after ~18 minutes of
    rendering with no backend calls in between) hit a 502 Bad Gateway
    because Render's free-tier backend had spun back down from idling
    during the render, and this POST had no retry, so 18 minutes of
    completed work was thrown away on a single transient gateway error.
    `files={"file": (...)}` opens the file handle fresh on each retry
    attempt by re-opening from the caller, so this wrapper takes a
    path instead of an open file handle to avoid resending an
    already-consumed/closed stream on retry.

    NOTE (2026-08-29): this wrapper only retries on 502/503/504 (Render
    gateway/cold-start symptoms). A 500 from the backend (e.g. the
    Supabase Storage upload inside upload_router.py failing and being
    surfaced as an unhandled 500) is NOT retried here on purpose - it's
    a real application-level failure, not a transient gateway issue, and
    retrying it blindly would just repeat the same failure 5 times. See
    TARGET_UPLOAD_MB comment above and the raised Supabase bucket
    file_size_limit for the actual fix to the 500 seen on video
    4fc244de-5e0d-4c36-91ab-825df9036085.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            file_path = kwargs.pop("_file_path")
            file_field_name = kwargs.pop("_file_field_name")
            with open(file_path, "rb") as f:
                files = {file_field_name: ("final.mp4", f, "video/mp4")}
                resp = requests.post(url, files=files, **kwargs)
            if resp.status_code in (502, 503, 504):
                raise requests.RequestException(
                    f"backend not ready yet (HTTP {resp.status_code})"
                )
            return resp
        except requests.RequestException as e:
            last_exc = e
            kwargs["_file_path"] = file_path
            kwargs["_file_field_name"] = file_field_name
            if attempt == max_attempts:
                break
            wait = min(15 * attempt, 60)
            print(f"Upload backend not ready (attempt {attempt}/{max_attempts}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise last_exc


def _parse_shots_count(production_plan):
    count = 0
    for line in production_plan.splitlines():
        line = line.strip()
        if SHOT_START.match(line):
            count += 1
    return count


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


def _resolve_durations(video, production_plan, total_shots):
    real = video.get("shot_durations")
    if real and len(real) >= total_shots:
        print(f"Using real shot_durations from narrate.py ({len(real)} shots, "
              f"summing to {sum(real[:total_shots]):.1f}s).")
        return [float(d) for d in real[:total_shots]]
    if real:
        print(f"shot_durations present but only covers {len(real)}/{total_shots} shots - "
              f"falling back to text-parsed planned durations.")
    else:
        print("No shot_durations on this video (narrated before the Edge TTS migration, or "
              "narration hasn't run yet) - falling back to text-parsed planned durations.")
    return _parse_durations(production_plan)


def _find_next_video_to_assemble():
    resp = _resilient_get(f"{RAILWAY_URL}/api/v1/videos", timeout=90)
    resp.raise_for_status()
    videos = resp.json()

    candidates = []
    for v in videos:
        if v.get("status") in ("assembled", "uploaded"):
            continue
        production_plan = v.get("production_plan")
        if not production_plan:
            continue
        total_shots = _parse_shots_count(production_plan)
        if total_shots == 0:
            continue
        clip_urls = v.get("clip_urls") or []
        if len(clip_urls) >= total_shots and all(clip_urls[:total_shots]):
            candidates.append(v)

    if not candidates:
        return None
    candidates.sort(key=lambda v: v.get("created_at") or "")
    return candidates[0]["id"]


def _download_file(url, dest_path, max_attempts=4):
    """FIX (2026-08-26): this was the only network call in the whole file
    with zero retry logic - every backend call already got retries on
    Aug 21-22 (see _resilient_get/_resilient_post), but this one didn't.
    One transient network hiccup pulling a clip from Supabase storage and
    the shot got silently dropped into `all_skipped` with no explanation
    printed anywhere. Confirmed live on "The Autumn of Fire": a handful of
    clip downloads failed silently this way, the assembled video track ran
    out after ~3-5 minutes of real footage, and the narration-vs-video
    freeze-hold mechanism at the end of main() (built for small
    end-of-video gaps) stretched to cover the rest of a 30-40 minute
    narration track - which is why it played as picture-frozen narration
    for the remainder. Supabase itself was NOT missing any data (all shots
    were filled) - this was purely a transient download failure during
    that one assembly run.

    Fix: retry with backoff (same pattern as _resilient_get/_resilient_post
    above), plus print a line on every failed attempt and a final failure
    line, so a real failure is visible in the run log instead of vanishing
    into all_skipped with zero explanation.
    """
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


def _still_image_clip(image_path, duration):
    target_w, target_h = RESOLUTION
    base_clip = ImageClip(image_path).set_duration(duration)
    src_w, src_h = base_clip.size
    cover_scale = max(target_w / src_w, target_h / src_h)

    def _scale(t):
        frac = (t / duration) if duration > 0 else 0.0
        return cover_scale * (1.0 + KEN_BURNS_ZOOM * frac)

    moving = base_clip.resize(_scale).set_position("center")
    framed = CompositeVideoClip([moving], size=RESOLUTION).set_duration(duration)
    framed = framed.crossfadein(min(CROSSFADE, duration / 2))
    return framed


def _fit_clip_to_duration(clip, target_duration, fps=24, shot_index=None):
    """FIX (2026-08-03): the old version of this file did
    `clip.set_duration(clip.duration)` when a downloaded clip was SHORTER
    than the shot's target duration - a no-op that silently left the shot
    under-filled instead of fixing anything.

    CHANGED (2026-08-29): previously, when a clip came back shorter than
    its target duration, this held the clip's final frame frozen for the
    remainder (a still-image "freeze-frame") to fill the gap. Zia flagged
    this freeze-frame as visible/unwanted at the end of shots. Since Agnes
    clips coming back short is common (see DIAGNOSTIC below), freezing was
    happening on most shots. Now: no freeze-frame is added - the shot
    simply plays for its actual real duration instead of being padded.
    This makes that shot slightly shorter on screen than planned, but
    removes the freeze entirely. (The separate CROSSFADE-loss fix in
    _render_block already compensates block-to-block timing independently
    of this function, so shortening a shot here does not reintroduce the
    old "video ends 30-50s early" bug - it only affects this one shot's
    own on-screen length.)

    DIAGNOSTIC (2026-08-16): Zia flagged a 0.5-0.8s freeze-hold on nearly
    EVERY scene, not occasionally - which points at Agnes systematically
    returning clips a bit shorter than the requested frame count, rather
    than a rare edge case. Logging every shot's (target, actual, pad) here
    so it's visible in the run log how often/how much this happens.
    """
    pad = max(target_duration - clip.duration, 0.0)
    _FREEZE_PAD_LOG.append((shot_index, target_duration, clip.duration, pad))
    if pad > 0:
        print(
            f"  [short-clip] shot {shot_index}: target={target_duration:.2f}s, "
            f"actual clip duration={clip.duration:.2f}s, playing at actual length "
            f"(no freeze-frame added, {pad:.2f}s shorter than planned)."
        )

    if clip.duration >= target_duration:
        return clip.subclip(0, target_duration)

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

    # FIX (2026-08-03): was `clip.set_duration(clip.duration)` here (a no-op)
    # when the clip came back shorter than needed - see _fit_clip_to_duration
    # docstring above. As of 2026-08-29, short clips play at their real
    # length instead of freeze-padding - see that function's docstring.
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


def _render_block(shot_indices, urls, durations, media_dir, block_output_path, use_clips):
    """
    CROSSFADE-LOSS FIX (2026-08-19): concatenate_videoclips() below uses
    padding=-CROSSFADE to create the crossfade transition between
    consecutive clips in this block - which OVERLAPS (and therefore trims)
    CROSSFADE seconds off the tail of every clip except the last one in
    the block. That overlap was never compensated for, so a block's
    assembled duration came out (num_shots_in_block - 1) * CROSSFADE
    seconds SHORTER than the sum of its shots' real target durations -
    invisible per-shot (each clip still reports its own correct duration
    going in) but compounding across every shot boundary in the video.
    This is the confirmed root cause of the 30-50s freeze at the end of
    assembled videos Zia flagged 2026-08-16: for an 80-shot video that's
    79 transitions * 0.5s = ~39.5s of duration lost to crossfade overlap
    - invisible until main()'s narration-vs-video length check at the
    very end pads the whole accumulated shortfall onto one giant frozen
    last frame (matches Red Moon Rising's ~40s freeze and Golden Horde's
    Tide's ~50s freeze almost exactly: 79 * 0.5 = 39.5s and 94 * 0.5 =
    47s respectively).

    Fix: every clip except the last one in its block now targets
    dur + CROSSFADE instead of dur, so after concatenate_videoclips()
    trims CROSSFADE off its tail via the negative-padding overlap, the
    VISIBLE on-screen duration lands back on the shot's real target - no
    accumulated loss, no oversized end-of-video freeze. This is separate
    from the per-shot short-clip handling (see _fit_clip_to_duration) and
    does not affect it - the freeze-pad diagnostic log below still
    reflects genuine Agnes-clip-came-back-short cases.
    """
    clips = []
    skipped = []
    errors = []
    last_index_in_block = shot_indices[-1] if shot_indices else None

    for i in shot_indices:
        url = urls[i]
        dur = durations[i]
        # See CROSSFADE-LOSS FIX docstring above: compensate every
        # non-last-in-block clip for the overlap trim it's about to take
        # during concatenate_videoclips() below.
        effective_dur = dur if i == last_index_in_block else dur + CROSSFADE
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
                clip = _video_clip(media_path, effective_dur, shot_index=i)
            else:
                clip = _still_image_clip(media_path, effective_dur)
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
        audio=use_clips,
        audio_codec="aac" if use_clips else None,
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


def _extract_native_audio(video_path, out_path):
    ok = _run_ffmpeg(
        ["-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", out_path],
        allow_fail=True,
    )
    if not ok or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        return None
    return out_path


def _get_video_duration(video_path):
    """FIX (2026-08-09): moviepy's VideoFileClip (via ffmpeg_reader) parses
    ffmpeg's probe output for a 'video_fps' field and raises KeyError when
    that field is missing - which happens on files produced by our own
    `ffmpeg -f concat -c copy` step earlier in this script, because stream
    copying can leave the container's fps metadata in a form moviepy's
    regex doesn't recognize. This crashed 70+ consecutive assemble runs
    at this exact line even though every real step (rendering, concat,
    audio mix) had already succeeded.

    Fix: read duration straight from ffmpeg's own text output instead of
    going through moviepy at all - ffmpeg always prints a 'Duration:
    HH:MM:SS.ms' line regardless of whether it can also parse fps, so this
    never depends on the missing field.
    """
    result = subprocess.run(
        [FFMPEG_BINARY, "-i", video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.decode(errors="ignore")
    match = FFMPEG_DURATION_PATTERN.search(output)
    if not match:
        raise RuntimeError(
            "Could not determine video duration from ffmpeg output for "
            + video_path + ". Last 1000 chars of ffmpeg output:\n"
            + output[-1000:]
        )
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _fit_audio_to_duration(audio_clip, target):
    if audio_clip.duration >= target:
        return audio_clip.subclip(0, target)
    reps = int(target // audio_clip.duration) + 1
    looped = concatenate_audioclips([audio_clip] * reps)
    return looped.subclip(0, target)


def _apply_safety_limiter(audio_clip, ceiling=LIMITER_CEILING):
    samples = audio_clip.to_soundarray(fps=44100)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0

    if peak <= 0 or peak <= ceiling:
        return audio_clip

    scale = ceiling / peak
    print(f"Safety limiter: peak was {peak:.3f}, exceeds ceiling {ceiling} - scaling mix by {scale:.3f}.")
    return audio_clip.volumex(scale)


def _build_mixed_audio(narration_path, native_sfx_path, out_path):
    narration_clip = AudioFileClip(narration_path)
    duration = narration_clip.duration

    extra_layers = []

    if native_sfx_path:
        print("Mixing in native clip audio (ambient/sfx/laughter from the source clips).")
        sfx_clip = AudioFileClip(native_sfx_path)
        sfx_clip = _fit_audio_to_duration(sfx_clip, duration)
        sfx_clip = sfx_clip.volumex(NATIVE_SFX_VOLUME)
        extra_layers.append(sfx_clip)
    else:
        print("No native clip audio detected to mix in for this video.")

    if extra_layers:
        narration_clip = narration_clip.volumex(NARRATION_VOLUME_WITH_LAYERS)
        layers = [narration_clip] + extra_layers
    else:
        print("Proceeding with narration-only audio for this video (full volume, no ducking).")
        layers = [narration_clip]

    mixed = CompositeAudioClip(layers).set_duration(duration)
    mixed = _apply_safety_limiter(mixed)
    mixed.write_audiofile(out_path, fps=44100, logger=None)

    for layer in layers:
        layer.close()
    mixed.close()
    return duration


def _compute_target_video_kbps(duration_seconds):
    total_kbps = (TARGET_UPLOAD_MB * 8000) / max(duration_seconds, 1)
    video_kbps = int(total_kbps - AUDIO_BITRATE_KBPS)
    return max(MIN_VIDEO_KBPS, video_kbps)


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    media_dir = os.path.join(WORK_DIR, "media")
    blocks_dir = os.path.join(WORK_DIR, "blocks")
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(blocks_dir, exist_ok=True)

    video_id = VIDEO_ID
    if not video_id:
        print("No VIDEO_ID provided - auto-selecting next video ready to assemble...")
        video_id = _find_next_video_to_assemble()
        if not video_id:
            print("No videos currently ready to assemble. Exiting cleanly.")
            return
        print(f"Auto-selected video_id: {video_id}")

    print("Fetching video data from Railway...")
    resp = _resilient_get(f"{RAILWAY_URL}/api/v1/videos/{video_id}", timeout=90)
    resp.raise_for_status()
    video = resp.json()

    clip_urls = video.get("clip_urls") or []
    asset_urls = video.get("asset_urls") or []
    production_plan = video.get("production_plan")
    title = video.get("title") or ""

    if not production_plan:
        print("ERROR: video has no production_plan")
        sys.exit(1)

    total_shots = _parse_shots_count(production_plan)
    if total_shots == 0:
        print("ERROR: no shots parsed from production_plan")
        sys.exit(1)

    if len(clip_urls) < total_shots or not all(clip_urls[:total_shots]):
        have = len([u for u in clip_urls[:total_shots] if u])
        print(
            f"NOT READY: this video needs {total_shots} real video clips but only has "
            f"{have} filled so far ({len(asset_urls)} still images are available as "
            f"reference only). Assembly will NOT fall back to still images - real Agnes "
            f"video clips are required for every shot. Let generate_videos.py finish "
            f"(it runs hourly, batches per run) until every shot has a clip, "
            f"then re-run assembly for this video."
        )
        return

    print(f"Found {len(clip_urls)} video clips - using real video clips for assembly.")
    use_clips = True
    urls = clip_urls

    print("Downloading narration audio from Railway...")
    audio_path = os.path.join(WORK_DIR, "narration.mp3")
    audio_resp = _resilient_get(
        f"{RAILWAY_URL}/api/v1/download/narration/{video_id}",
        headers=HEADERS,
        timeout=60,
    )
    audio_resp.raise_for_status()
    with open(audio_path, "wb") as f:
        f.write(audio_resp.content)

    durations = _resolve_durations(video, production_plan, total_shots)
    n = min(len(urls), len(durations))
    if n == 0:
        print("ERROR: no shots to assemble")
        sys.exit(1)
    urls = urls[:n]
    durations = durations[:n]

    silent_path = os.path.join(WORK_DIR, "silent_final.mp4")
    native_sfx_path = os.path.join(WORK_DIR, "native_sfx.wav")
    mixed_audio_path = os.path.join(WORK_DIR, "mixed_audio.wav")
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

    # DIAGNOSTIC (2026-08-16): summarize freeze-pad across the whole run so
    # this is visible without scrolling through per-shot logs.
    if _FREEZE_PAD_LOG:
        padded = [x for x in _FREEZE_PAD_LOG if x[3] > 0]
        total = len(_FREEZE_PAD_LOG)
        avg_pad = (sum(x[3] for x in padded) / len(padded)) if padded else 0.0
        print(
            f"[short-clip SUMMARY] {len(padded)}/{total} shots this run came back shorter "
            f"than planned (avg shortfall where short: {avg_pad:.2f}s). These play at their "
            f"real length now (no freeze-frame added)."
        )

    with open(concat_list_path, "w") as f:
        for p in block_paths:
            safe_p = p.replace("'", "'\\''")
            f.write("file '" + safe_p + "'\n")

    print("Concatenating video blocks...")
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", silent_path])

    print("Extracting native clip audio (ambient/sfx/laughter) for the mix...")
    extracted_sfx = _extract_native_audio(silent_path, native_sfx_path)

    print("Building audio mix (narration + native clip audio)...")
    total_duration = _build_mixed_audio(audio_path, extracted_sfx, mixed_audio_path)

    video_duration = _get_video_duration(silent_path)
    # END-FREEZE FIX (2026-08-26): the target held-through duration now
    # includes END_FREEZE_SECONDS, so the finished video always settles
    # on the last frame for a beat after narration ends instead of
    # cutting the instant the last word/shot finishes. This is separate
    # from the CROSSFADE=0.5s scene-to-scene transitions above - it only
    # affects the single tail-end of the fully assembled video, not any
    # point between shots.
    target_duration = total_duration + END_FREEZE_SECONDS
    pad_seconds = target_duration - video_duration
    if pad_seconds > 0.5:
        print(
            f"Video track ({video_duration:.1f}s) is shorter than narration + "
            f"end-freeze ({target_duration:.1f}s) - freezing the last frame for "
            f"an extra {pad_seconds:.1f}s (includes {END_FREEZE_SECONDS}s end-hold) "
            f"so no narration gets cut off and the video settles before ending."
        )
        cinematic_vf = f"tpad=stop_mode=clone:stop_duration={pad_seconds:.2f}," + CINEMATIC_VF_BASE
    else:
        cinematic_vf = CINEMATIC_VF_BASE

    video_kbps = _compute_target_video_kbps(target_duration)
    print(
        f"Applying cinematic grade and merging mixed audio "
        f"(duration={target_duration:.1f}s, target video bitrate={video_kbps}kbps, "
        f"budget={TARGET_UPLOAD_MB}MB)..."
    )
    _run_ffmpeg([
        "-i", silent_path,
        "-i", mixed_audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-vf", cinematic_vf,
        "-af", LOUDNORM_AF,
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.45)}k",
        "-bufsize", f"{int(video_kbps * 2)}k",
        "-c:a", "aac",
        "-b:a", f"{AUDIO_BITRATE_KBPS}k",
        # CHANGED (2026-08-26): was "-shortest", which capped the final
        # output at narration length and silently discarded the new
        # end-freeze extension (video track ran longer than audio, so
        # "-shortest" cut it right back down to audio length - the freeze
        # would have been added and then immediately thrown away). "-t"
        # with the explicit target duration keeps the added hold; audio
        # simply ends in silence for the last END_FREEZE_SECONDS, which is
        # correct for a freeze-frame with no dialogue happening over it.
        "-t", f"{target_duration:.2f}",
        final_path,
    ])


    final_size_mb = os.path.getsize(final_path) / (1024 * 1024)
    print(f"Final file size: {final_size_mb:.1f}MB (budget was {TARGET_UPLOAD_MB}MB)")

    print("Uploading finished video back to Railway...")
    upload_resp = _resilient_post(
        f"{RAILWAY_URL}/api/v1/upload/video/{video_id}",
        headers=HEADERS,
        timeout=300,
        _file_path=final_path,
        _file_field_name="file",
    )
    upload_resp.raise_for_status()

    print("SUCCESS:", upload_resp.json())
    if all_errors:
        print("Note: some shots had issues:", all_errors)


def _print_failure_summary(exc):
    import traceback
    tb = traceback.extract_tb(exc.__traceback__)
    location = "unknown"
    for frame in tb:
        if frame.filename.endswith("assemble.py"):
            location = f"{frame.name}() line {frame.lineno}"
    print("\n" + "=" * 60)
    print("FAILURE SUMMARY (read this first)")
    print("=" * 60)
    print(f"Script:        assemble.py")
    print(f"Failed in:     {location}")
    print(f"Error type:    {type(exc).__name__}")
    print(f"Error message: {str(exc)[:400]}")
    print(f"RAILWAY_URL:   {RAILWAY_URL}")
    print(f"VIDEO_ID:      {VIDEO_ID or '(auto-select)'}")
    print("=" * 60)
    print("Full traceback follows below for reference.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _print_failure_summary(e)
        raise
