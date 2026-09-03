import gc
import hashlib
import os
import re
import subprocess
import sys
import threading
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

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
RELEASE_TAG = "nova-video-storage"

if not GITHUB_TOKEN:
    print(
        "FATAL: GITHUB_TOKEN is missing or empty. This must be set as an "
        "env var on the 'Run assembly' step in assemble.yml (use "
        "${{ secrets.GITHUB_TOKEN }} - no new secret needs to be created, "
        "GitHub provides this automatically on every run) - assembly "
        "cannot create/upload a release asset without it."
    )
    sys.exit(1)
if not GITHUB_REPOSITORY or "/" not in GITHUB_REPOSITORY:
    print(
        "FATAL: GITHUB_REPOSITORY is missing or malformed (got: "
        f"{GITHUB_REPOSITORY!r}). GitHub Actions sets this automatically - "
        "if it's missing, this script is not running inside a normal "
        "GitHub Actions job."
    )
    sys.exit(1)

FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "").strip()
FREESOUND_ENABLED = bool(FREESOUND_API_KEY)
FREESOUND_SEARCH_URL = "https://freesound.org/apiv2/search/text/"
SFX_VOLUME = 0.22
SFX_MAX_SEARCHES_PER_RUN = 60

DEFAULT_SHOT_DURATION = 3.0
CROSSFADE = 0.5
RESOLUTION = (1920, 1080)
BLOCK_SIZE = 10
KEN_BURNS_ZOOM = 0.08

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

NATIVE_SFX_VOLUME = 0.16
NARRATION_VOLUME_WITH_LAYERS = 0.92
LIMITER_CEILING = 0.98

MUSIC_ENABLED = True
MUSIC_VOLUME = 0.10
MUSIC_CROSSFADE = 2.0
MUSIC_BASE_URL = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
MUSIC_ATTRIBUTION = (
    "Music by Kevin MacLeod (incompetech.com), licensed under Creative "
    "Commons: By Attribution 3.0 (creativecommons.org/licenses/by/3.0/) - "
    "attribution is added to every video's YouTube description "
    "unconditionally by youtube_upload.py's MUSIC_ATTRIBUTION_LINE / "
    "_build_final_description() (confirmed live 2026-09-03) - this "
    "script has no way to write to the YouTube description itself, so "
    "the actual attribution placement lives in that file, not here."
)
_MUSIC_CHAPTERS = [
    ("Cold Open", "tense_mysterious", "The-Cannery.mp3"),
    ("Problem/Stakes", "moody_dread", "Ossuary-6-Air.mp3"),
    ("Rising Delivery", "building_tension", "Long-Note-One.mp3"),
    ("Midpoint Twist", "dramatic_shift", "Rite-of-Passage.mp3"),
    ("Climax", "intense_epic", "Impact-Moderato.mp3"),
    ("Payoff", "resolving_uplifting", "Thoughtful.mp3"),
]

WORK_DIR = "/tmp/nova_assembly"
FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

SHOT_START = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)
DURATION_PATTERN = re.compile(r"Duration\*{0,2}\s*:\s*\*{0,2}\s*([\d.]+)\s*s", re.IGNORECASE)
FFMPEG_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
SFX_PATTERN = re.compile(r"SFX\*{0,2}\s*:\s*\*{0,2}\s*([^\n]+)", re.IGNORECASE)

HEADERS = {"X-Assembly-Secret": ASSEMBLY_SECRET}

_FREEZE_PAD_LOG = []

_KEEPALIVE_STOP = threading.Event()


def _keepalive_loop():
    while not _KEEPALIVE_STOP.wait(300):
        try:
            requests.get(f"{RAILWAY_URL}/health", timeout=30)
        except requests.RequestException:
            pass


def _start_keepalive():
    t = threading.Thread(target=_keepalive_loop, daemon=True)
    t.start()
    return t


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


def _resilient_patch_json(url, json_body, max_attempts=5, timeout=60):
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.patch(url, json=json_body, timeout=timeout)
            if resp.status_code in (502, 503, 504):
                raise requests.RequestException(
                    f"backend not ready yet (HTTP {resp.status_code})"
                )
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt == max_attempts:
                break
            wait = min(15 * attempt, 60)
            print(f"Status PATCH backend not ready (attempt {attempt}/{max_attempts}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise last_exc


def _github_api_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_or_create_release():
    get_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/tags/{RELEASE_TAG}"
    resp = requests.get(get_url, headers=_github_api_headers(), timeout=30)
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code != 404:
        raise RuntimeError(f"Failed to look up release '{RELEASE_TAG}' ({resp.status_code}): {resp.text[:500]}")

    create_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases"
    resp = requests.post(
        create_url,
        headers=_github_api_headers(),
        json={
            "tag_name": RELEASE_TAG,
            "name": "Nova video storage (do not delete)",
            "body": "Internal storage bucket for finished Nova videos, used by assemble.py "
                     "and youtube_upload.py as a free Supabase-Storage replacement. Each "
                     "asset is deleted automatically right after its video is confirmed "
                     "uploaded to YouTube, so this should normally sit empty or near-empty.",
            "draft": False,
            "prerelease": False,
        },
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Failed to create release '{RELEASE_TAG}' ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


def _delete_existing_asset_if_present(release, asset_name):
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            del_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/assets/{asset['id']}"
            requests.delete(del_url, headers=_github_api_headers(), timeout=30)


def _upload_final_video_to_github_release(video_id, file_path):
    asset_name = f"{video_id}.mp4"
    release = _get_or_create_release()
    _delete_existing_asset_if_present(release, asset_name)

    upload_base = release["upload_url"].split("{")[0]
    upload_url = f"{upload_base}?name={asset_name}"
    file_size = os.path.getsize(file_path)

    headers = {
        **_github_api_headers(),
        "Content-Type": "video/mp4",
        "Content-Length": str(file_size),
    }

    last_exc = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(upload_url, headers=headers, data=f, timeout=900)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"GitHub Release asset upload failed ({resp.status_code}): {resp.text[:500]}"
                )
            return resp.json()["browser_download_url"]
        except (requests.RequestException, RuntimeError) as e:
            last_exc = e
            if attempt == max_attempts:
                break
            wait = 20 * attempt
            print(f"Direct-to-GitHub-Release upload attempt {attempt}/{max_attempts} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Direct-to-GitHub-Release upload failed after {max_attempts} attempts: {last_exc}")


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
        print(f"  [sfx] per-run search cap ({SFX_MAX_SEARCHES_PER_RUN}) reached - "
              f"'{keyword}' will have no SFX layer this run.")
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
            print(f"  [sfx] search failed for '{keyword}' (HTTP {resp.status_code}) - no SFX for this shot.")
            _sfx_cache[cache_key] = None
            return None

        results = resp.json().get("results") or []
        if not results:
            print(f"  [sfx] no Freesound results for '{keyword}' - no SFX for this shot.")
            _sfx_cache[cache_key] = None
            return None

        preview_url = (results[0].get("previews") or {}).get("preview-hq-mp3")
        if not preview_url:
            print(f"  [sfx] result for '{keyword}' had no usable preview - no SFX for this shot.")
            _sfx_cache[cache_key] = None
            return None

        safe_name = hashlib.md5(cache_key.encode()).hexdigest()[:12]
        dest_path = os.path.join(work_dir, f"sfx_{safe_name}.mp3")
        dl_resp = requests.get(preview_url, timeout=30)
        if dl_resp.status_code != 200 or len(dl_resp.content) == 0:
            print(f"  [sfx] preview download failed for '{keyword}' - no SFX for this shot.")
            _sfx_cache[cache_key] = None
            return None

        with open(dest_path, "wb") as f:
            f.write(dl_resp.content)
        _sfx_cache[cache_key] = dest_path
        return dest_path
    except Exception as e:
        print(f"  [sfx] lookup failed for '{keyword}' ({type(e).__name__}: {e}) - no SFX for this shot.")
        _sfx_cache[cache_key] = None
        return None


def _build_sfx_bed(sfx_keywords, durations, work_dir):
    if not FREESOUND_ENABLED:
        return None

    segments = []
    t = 0.0
    for keyword, dur in zip(sfx_keywords, durations):
        sfx_path = _fetch_shot_sfx(keyword, work_dir) if keyword else None
        if sfx_path:
            try:
                clip = AudioFileClip(sfx_path).volumex(SFX_VOLUME)
                if clip.duration > dur:
                    clip = clip.subclip(0, dur)
                clip = clip.set_start(t)
                segments.append(clip)
            except Exception as e:
                print(f"  [sfx] failed to load fetched clip for shot at t={t:.1f}s "
                      f"({type(e).__name__}: {e}) - skipping this shot's SFX.")
        t += dur

    if not segments:
        print("  [sfx] no usable SFX this run (disabled, no keywords, or every lookup failed) - "
              "proceeding without an SFX layer.")
        return None

    total_duration = t
    bed = CompositeAudioClip(segments).set_duration(total_duration)
    print(f"  [sfx] built SFX bed from {len(segments)}/{len(sfx_keywords)} shots "
          f"({_sfx_search_count} Freesound searches this run).")
    return bed


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
    """Short clips (Agnes returning fewer frames than requested) play at
    their real, shorter length instead of freeze-padding to fill the gap -
    see FREEZE-FRAME ELIMINATION note near main() for the full history.
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
    clips = []
    skipped = []
    errors = []
    last_index_in_block = shot_indices[-1] if shot_indices else None

    for i in shot_indices:
        url = urls[i]
        dur = durations[i]
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


def _download_music_track(filename, dest_path):
    url = MUSIC_BASE_URL + filename
    ok = _download_file(url, dest_path, max_attempts=2)
    return dest_path if ok else None


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
            track_path = _download_music_track(filename, track_path)
        if not track_path:
            print(f"  [music] '{label}' ({mood}) track failed to download - that segment will be silent.")
            continue

        try:
            raw_clip = AudioFileClip(track_path)
            fitted = _fit_audio_to_duration(raw_clip, seg_duration).volumex(MUSIC_VOLUME)
            if pre > 0:
                fitted = fitted.audio_fadein(MUSIC_CROSSFADE)
            if post > 0:
                fitted = fitted.audio_fadeout(MUSIC_CROSSFADE)
            fitted = fitted.set_start(seg_start)
            segments.append(fitted)
        except Exception as e:
            print(f"  [music] '{label}' track failed to load ({type(e).__name__}: {e}) - that segment will be silent.")
            continue

    if not segments:
        print("  [music] no chapter tracks available this run - proceeding without a music bed.")
        return None

    bed = CompositeAudioClip(segments).set_duration(total_duration)
    print(f"  [music] built music bed from {len(segments)}/{n} chapter cues. {MUSIC_ATTRIBUTION}")
    return bed


def _build_mixed_audio(narration_path, native_sfx_path, music_clip, shot_sfx_clip, out_path):
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

    if shot_sfx_clip:
        print("Mixing in per-shot scripted SFX (Freesound).")
        shot_sfx_clip = _fit_audio_to_duration(shot_sfx_clip, duration)
        extra_layers.append(shot_sfx_clip)
    else:
        print("No per-shot scripted SFX available to mix in for this video.")

    if music_clip:
        print("Mixing in chapter music bed.")
        extra_layers.append(music_clip)

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


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    media_dir = os.path.join(WORK_DIR, "media")
    blocks_dir = os.path.join(WORK_DIR, "blocks")
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(blocks_dir, exist_ok=True)

    if not FREESOUND_ENABLED:
        print("FREESOUND_API_KEY not set - per-shot SFX layer will be skipped this run "
              "(music and native-clip audio are unaffected). Get a free token at "
              "https://freesound.org/apiv2/apply/ and add it as a repo secret to enable.")

    _start_keepalive()

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
    sfx_keywords = _parse_sfx_keywords(production_plan, total_shots)[:n]

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

    print("Determining narration duration for chapter music timing...")
    narration_duration_probe = AudioFileClip(audio_path).duration

    print("Building chapter music bed...")
    music_bed = None
    try:
        music_bed = _build_music_bed(narration_duration_probe, WORK_DIR)
    except Exception as e:
        print(f"  [music] music bed build failed entirely ({type(e).__name__}: {e}) - continuing without music.")

    print("Building per-shot scripted SFX bed (Freesound)...")
    shot_sfx_bed = None
    try:
        shot_sfx_bed = _build_sfx_bed(sfx_keywords, durations, media_dir)
    except Exception as e:
        print(f"  [sfx] SFX bed build failed entirely ({type(e).__name__}: {e}) - continuing without per-shot SFX.")

    print("Building audio mix (narration + native clip audio + per-shot SFX + chapter music)...")
    total_duration = _build_mixed_audio(audio_path, extracted_sfx, music_bed, shot_sfx_bed, mixed_audio_path)

    video_duration = _get_video_duration(silent_path)

    # FREEZE-FRAME ELIMINATED ENTIRELY (2026-09-03, hard requirement -
    # zero tolerance for any frozen-frame padding anywhere in the final
    # video, per Zia's explicit instruction). This removes BOTH remaining
    # freeze-frame codepaths that existed before this change:
    #   1. The deliberate END_FREEZE_SECONDS=0.75s hold tacked onto the
    #      very end of the video (added 2026-08-26).
    #   2. The tpad=stop_mode=clone safety-net that froze the last frame
    #      whenever the assembled video track came up shorter than
    #      narration+end-hold (whatever residual gap remained after the
    #      2026-08-19 crossfade-loss fix and the 2026-08-29 per-shot
    #      short-clip fix).
    # Replacement: ffmpeg's "-shortest" flag, which simply ends the output
    # at whichever of video/audio is shorter. This makes a frozen frame
    # STRUCTURALLY IMPOSSIBLE - there is no codepath left that clones or
    # holds a frame under any condition. The only behavior change is that
    # if the video track and narration differ by a fraction of a second
    # (which _resolve_durations's real per-shot shot_durations from
    # narrate.py should already keep near-zero), the output simply ends at
    # the shorter of the two instead of freezing to cover the gap.
    cinematic_vf = CINEMATIC_VF_BASE

    print(
        f"Applying cinematic grade and merging mixed audio "
        f"(video={video_duration:.1f}s, narration={total_duration:.1f}s, ending at "
        f"whichever is shorter - no freeze-frame padding, CRF={VIDEO_CRF})..."
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
        "-crf", str(VIDEO_CRF),
        "-c:a", "aac",
        "-b:a", f"{AUDIO_BITRATE_KBPS}k",
        "-shortest",
        final_path,
    ])


    final_size_mb = os.path.getsize(final_path) / (1024 * 1024)
    print(f"Final file size: {final_size_mb:.1f}MB (CRF {VIDEO_CRF}, no size budget applied).")

    print("Uploading finished video to a GitHub Release asset (free, no size ceiling, no quality change)...")
    video_url = _upload_final_video_to_github_release(video_id, final_path)
    print(f"Uploaded to GitHub Release: {video_url}")

    print("Marking video as assembled on the backend (small JSON PATCH, no file transfer)...")
    patch_resp = _resilient_patch_json(
        f"{RAILWAY_URL}/api/v1/videos/{video_id}",
        {"status": "assembled", "video_url": video_url},
    )
    patch_resp.raise_for_status()

    print("SUCCESS:", patch_resp.json())
    if all_errors:
        print("Note: some shots had issues:", all_errors)

    _KEEPALIVE_STOP.set()


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
    finally:
        _KEEPALIVE_STOP.set()
