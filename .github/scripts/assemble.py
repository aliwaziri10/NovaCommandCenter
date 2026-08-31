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

# ADDED (2026-08-31): DIRECT-TO-SUPABASE UPLOAD FIX.
# ROOT CAUSE CONFIRMED via two matched production runs on the exact same
# video (b43ac407-...): run #356 (pre-CRF, 400kbps/35MB budget) produced a
# 48.1MB file and uploaded successfully. Run #357 (post-CRF-20 change,
# same video, same shots, same narration) produced a 743.7MB file and
# failed on upload with HTTP 502, four separate times, on every retry.
# A second, different video (4fc244de, 56 shots) independently produced
# 659.2MB and failed identically across at least two separate runs (#359,
# #360) hours apart - including one run that started *after* the
# keep-alive and PUT-timeout fixes were already live, which rules out
# cold-start as the cause. The one variable that changed between "always
# worked" and "always fails" is file size, not timing.
# Render's free-tier backend runs on very limited RAM. A 650-750MB upload
# arriving as a single multipart POST is a highly plausible way to OOM-
# crash that process on every attempt, warm or not - which surfaces to
# the client as an opaque 502, indistinguishable from a cold start unless
# you're looking at Render's own crash logs.
# Fix: this script now uploads the finished video file directly from the
# GitHub Actions runner to Supabase Storage (same bucket the backend
# already uses), completely bypassing Render for the large-file transfer.
# The backend is then updated with a single small JSON PATCH
# (~100 bytes: status + the resulting public URL) via the existing
# generic /api/v1/videos/{id} CRUD endpoint - the same pattern
# youtube_upload.py already uses to mark a video as uploaded. This keeps
# CRF 20 (no quality compromise) while removing Render's free-tier RAM
# entirely from the critical path for this step.
# Requires SUPABASE_URL and SUPABASE_SECRET_KEY as env vars on this
# workflow (same values already set on the Render backend service) - see
# assemble.yml.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE_BUCKET = "nova-media"

# ADDED (2026-08-31, fail-fast diagnostic): the direct-to-Supabase upload
# path introduced same day silently produces a malformed upload URL (and
# an opaque downstream exception, not a clear error) if these two secrets
# are referenced in assemble.yml but were never actually created in repo
# Settings -> Secrets, or were left blank. Confirmed via the commit
# timeline that assemble.yml wasn't wired to pass these secrets at all
# for the first ~27 minutes after this code went live (issue #140), and
# two further unexplained failures (#141, #142) followed even after the
# yml was patched - consistent with the secrets being referenced in the
# yml but not actually set with real values in GitHub. This check turns
# that into an immediate, unambiguous failure message instead of a
# confusing requests/URL exception several steps later.
if not SUPABASE_URL or not SUPABASE_URL.startswith("http"):
    print(
        "FATAL: SUPABASE_URL is missing or not a valid URL (got: "
        f"{SUPABASE_URL!r}). This must be set as a repo secret "
        "(Settings -> Secrets and variables -> Actions -> SUPABASE_URL) "
        "with the project's real Supabase URL, e.g. "
        "https://<project-ref>.supabase.co - assembly cannot upload "
        "without it."
    )
    sys.exit(1)
if not SUPABASE_SECRET_KEY:
    print(
        "FATAL: SUPABASE_SECRET_KEY is missing or empty. This must be "
        "set as a repo secret (Settings -> Secrets and variables -> "
        "Actions -> SUPABASE_SECRET_KEY) - assembly cannot authenticate "
        "to Supabase Storage without it."
    )
    sys.exit(1)

# ADDED (2026-08-31, SFX refinement pass): Freesound.org API for real,
# per-shot sound effects. Freesound was chosen after checking 10 options
# for a free, automatable SFX source (video-conditioned generative APIs
# like Sonilo/ElevenLabs SFX are commercial-only or have quota far too
# small for daily volume; YouTube Audio Library and the BBC SFX archive
# have no public API; self-hosted generative audio models need GPU compute
# this pipeline's free-tier infra doesn't have). Freesound's own published
# API docs (freesound.org/docs/api/overview.html) confirm a real free
# tier: 60 requests/minute, 2000 requests/day, simple token-based auth (no
# OAuth2 needed for searching or downloading preview-quality mp3/ogg files
# - OAuth2 is only required for original-quality downloads, which this
# pipeline doesn't need). At ~1-2 videos/day with a few dozen SFX cues
# each, this pipeline is nowhere near either limit.
# Requires FREESOUND_API_KEY as an env var (apply for a free token at
# https://freesound.org/apiv2/apply/) - see assemble.yml. SFX is treated
# as fully optional, same as music: any lookup/download failure for a
# given shot just means that shot has no SFX layer, never a hard failure.
FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "").strip()
FREESOUND_ENABLED = bool(FREESOUND_API_KEY)
FREESOUND_SEARCH_URL = "https://freesound.org/apiv2/search/text/"
SFX_VOLUME = 0.22
# Cap on unique Freesound searches per assembly run - a 100-shot video
# would otherwise fire up to 100 searches; most shots share similar SFX
# keywords (e.g. many "footsteps stone floor" shots in one script), so a
# small in-run cache (see _fetch_shot_sfx) already collapses most repeats.
# This is a hard ceiling as a second safety net against an unusually
# keyword-diverse script eating into the 2000/day budget in one run.
SFX_MAX_SEARCHES_PER_RUN = 60

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

# REMOVED (2026-08-30): TARGET_UPLOAD_MB / MIN_VIDEO_KBPS bitrate-budget
# system removed entirely. Confirmed by direct calculation that it was
# doing nothing useful: for this pipeline's typical ~870s video length,
# BOTH the old 45MB budget and the "fixed" 35MB budget computed a video
# kbps below MIN_VIDEO_KBPS=400, so the 400kbps floor silently overrode
# the budget on every single run - that's why final file size barely
# moved (53.9MB -> 53.8MB -> 53.9MB) when the budget was "lowered" from
# 45 to 35 on 2026-08-29. 400kbps at 1920x1080 is far below YouTube's own
# ~8000kbps guidance for 1080p30 SDR uploads - this pipeline has been
# rendering visibly under-quality 1080p this whole time, independent of
# the earlier upload-failure bug.
#
# Zia wants no compromise on 1080p quality. A file-size budget and real
# quality are in tension for a video this long (870s), so this now uses
# CRF (constant quality) encoding instead of a bitrate target - standard
# practice for "give me good quality" without guessing a bitrate number.
# The Supabase bucket limit has separately been raised to 500MB
# (2026-08-30) to comfortably fit whatever CRF 20 produces at this
# length, and the upload path no longer double-buffers the full file in
# memory (see upload_router.py/supabase_storage.py, same date) so a
# larger file doesn't add OOM risk on Render's free-tier instance.
# NOTE (2026-08-31): that OOM-risk mitigation in upload_router.py helped
# but was not sufficient on its own - see DIRECT-TO-SUPABASE UPLOAD note
# above. This CRF choice itself is unchanged and is not being walked back;
# only how the resulting large file gets uploaded has changed.
VIDEO_CRF = 20  # visually near-lossless for x264; lower = higher quality/larger file
AUDIO_BITRATE_KBPS = 128
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
# LOWERED (2026-08-31): was 0.95. Now that a real per-shot SFX layer
# (SFX_VOLUME) exists in addition to native clip audio and music, three
# simultaneous layers under narration need slightly more headroom each to
# avoid a muddier mix than the old two-layer (native + music) version -
# the safety limiter below still catches any residual peak overage.
NARRATION_VOLUME_WITH_LAYERS = 0.92
LIMITER_CEILING = 0.98

# ADDED (2026-08-30, NOVA_REBUILD_HANDOFF.md item #6): music cue/mood
# shift at every chapter boundary. Chapter boundaries are derived from the
# same fixed timing spine already baked into script_writing_agent.py's
# Rule 0 (Curiosity Loop six-beat structure / Hook-Problem-Solution-Payoff
# spine) - NOT from parsing `[CHAPTER: ...]` markers out of the script
# text. There is currently no mapping from a chapter marker's position in
# the script to a timestamp in the assembled video (shots are planned
# separately from the script by video_planning_agent), so deriving cue
# points from Rule 0's already-fixed percentage/second targets is the only
# reliable timing source assemble.py has today. If a real chapter-to-shot
# mapping gets built later, swap the fixed fractions in
# _chapter_time_bounds() below for that instead - everything downstream
# (crossfade, mixing) stays the same.
#
# Tracks are Kevin MacLeod / incompetech.com, Creative Commons BY 3.0 -
# free to use, only requires attribution (fits the zero-budget
# constraint). Filenames below follow incompetech's standard download
# naming but have not been individually re-verified live - if a track
# fails to download, that chapter's segment is simply silent instead of
# failing the whole assembly (see _build_music_bed), so a bad filename
# degrades gracefully and will show up as a "[music] ... failed to
# download" line in the run log rather than breaking anything. Swap any
# filename that shows up failing repeatedly.
MUSIC_ENABLED = True
MUSIC_VOLUME = 0.10
MUSIC_CROSSFADE = 2.0
MUSIC_BASE_URL = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
MUSIC_ATTRIBUTION = (
    "Music by Kevin MacLeod (incompetech.com), licensed under Creative "
    "Commons: By Attribution 3.0 (creativecommons.org/licenses/by/3.0/) - "
    "STILL NEEDS TO BE ADDED to every video description by youtube_upload.py "
    "(not done as part of this change - separate follow-up)."
)
# (chapter label, mood, incompetech filename) - one per Curiosity Loop beat,
# in order (Cold Open, Problem/Stakes, Rising Delivery, Midpoint Twist,
# Climax, Payoff).
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
# ADDED (2026-08-31, SFX refinement pass): matches the "SFX: <keyword>"
# line video_planning_agent.py now requires per shot (see that file's
# SFX_LINE_RULE). Mirrors DURATION_PATTERN's tolerance for markdown-bold
# wrapping (Gemini sometimes wraps field labels in ** even when told not
# to), since that's already proven necessary for the Duration line.
SFX_PATTERN = re.compile(r"SFX\*{0,2}\s*:\s*\*{0,2}\s*([^\n]+)", re.IGNORECASE)

HEADERS = {"X-Assembly-Secret": ASSEMBLY_SECRET}

# DIAGNOSTIC (2026-08-16): accumulates every shot's (target, actual, pad)
# across the whole run so we can print a summary at the end confirming or
# ruling out "Agnes systematically returns clips shorter than requested"
# the cause of near-universal freeze-hold padding at scene ends.
_FREEZE_PAD_LOG = []

# KEEP-ALIVE FIX (2026-08-30): confirmed live on video 4fc244de - the
# upload-cold-start retry logic added 2026-08-22 (_resilient_post) handles
# a SHORT idle gap before upload, but this run did ~56 minutes of pure
# local ffmpeg rendering with ZERO requests to the backend in between,
# which is well past Render free tier's ~15 min inactivity spin-down
# window. By the time the final upload POST fired, the backend had been
# asleep for 40+ minutes, and even 4 retries with backoff (15/30/45/60s =
# 150s total) weren't reliable margin to cover both a full cold start AND
# transferring a 53.9MB body - confirmed failing 4/4 attempts on run
# https://github.com/aliwaziri10/NovaCommandCenter/actions/runs/33268...
# (video 4fc244de, 2026-08-30).
#
# Retrying harder after the backend has already gone to sleep is treating
# the symptom. The actual fix is to never let it go to sleep during the
# render in the first place: a background thread pings the cheap /health
# endpoint every 5 minutes for as long as main() is doing local work, so
# Render's 15-minute inactivity clock never completes a full cycle and
# the backend is already warm for the small metadata calls this script
# still makes to it (video fetch, narration download, final status PATCH).
# NOTE (2026-08-31): this thread is still useful - it just no longer needs
# to keep the backend warm for a giant file upload, only for the small
# calls that remain. Left in place unchanged.
_KEEPALIVE_STOP = threading.Event()


def _keepalive_loop():
    while not _KEEPALIVE_STOP.wait(300):  # 5 minutes
        try:
            requests.get(f"{RAILWAY_URL}/health", timeout=30)
        except requests.RequestException:
            pass  # best-effort only - _resilient_post still covers a genuine cold start


def _start_keepalive():
    t = threading.Thread(target=_keepalive_loop, daemon=True)
    t.start()
    return t


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


def _resilient_patch_json(url, json_body, max_attempts=5, timeout=60):
    """ADDED (2026-08-31): small-body version of _resilient_get's retry
    pattern, for the final status-update PATCH to the backend (see
    DIRECT-TO-SUPABASE UPLOAD note above). This request is tiny (a JSON
    object with a status string and a URL) so cold-start/gateway retries
    are cheap here in a way they were never cheap for the old full-file
    POST - there's no multi-hundred-MB body to re-send on every retry.
    """
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


def _upload_final_video_to_supabase(video_id, file_path):
    """ADDED (2026-08-31): uploads the finished, fully-assembled video
    file DIRECTLY from this GitHub Actions runner to Supabase Storage,
    bypassing Render entirely for this transfer - see DIRECT-TO-SUPABASE
    UPLOAD note near the top of this file for why. Streams the file from
    disk (not loaded fully into memory first) since this runner's own
    memory is also finite, though far less constrained than Render's
    free tier. Mirrors the same bucket/path convention the backend's own
    upload_to_storage() uses (backend/app/supabase_storage.py) so the
    resulting public URL is indistinguishable from one the backend would
    have produced itself.

    Raises RuntimeError with Supabase's actual error text on failure -
    matches the "never fail silently" principle from supabase_storage.py.
    """
    path_in_bucket = f"final/{video_id}.mp4"
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path_in_bucket}"
    file_size = os.path.getsize(file_path)

    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "video/mp4",
        "Content-Length": str(file_size),
        "x-upsert": "true",
    }

    last_exc = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with open(file_path, "rb") as f:
                resp = requests.put(upload_url, headers=headers, data=f, timeout=900)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Supabase Storage upload failed ({resp.status_code}): {resp.text[:500]}"
                )
            return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{path_in_bucket}"
        except (requests.RequestException, RuntimeError) as e:
            last_exc = e
            if attempt == max_attempts:
                break
            wait = 20 * attempt
            print(f"Direct-to-Supabase upload attempt {attempt}/{max_attempts} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Direct-to-Supabase upload failed after {max_attempts} attempts: {last_exc}")


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
    """ADDED (2026-08-31, SFX refinement pass): extracts each shot's
    'SFX: <keyword>' line (see video_planning_agent.py's SFX_LINE_RULE) in
    shot order, mirroring _parse_durations's line-scanning approach exactly
    so shot indices stay aligned between durations and SFX keywords. A shot
    with no SFX line (e.g. an older plan generated before this feature, or
    one the bounded retry in video_planning_agent.py didn't fully fix)
    simply gets None here, which _fetch_shot_sfx treats as "no SFX for this
    shot" rather than an error - old plans and partially-covered plans both
    still assemble normally, just without SFX on the affected shots."""
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
    # First entry is a None placeholder from before the first shot started -
    # drop it, then pad/truncate to total_shots so this always lines up
    # 1:1 with _parse_durations's output length.
    keywords = keywords[1:] if keywords and keywords[0] is None and len(keywords) > total_shots else keywords
    while len(keywords) < total_shots:
        keywords.append(None)
    return keywords[:total_shots]


_sfx_cache = {}
_sfx_search_count = 0


def _fetch_shot_sfx(keyword, work_dir):
    """ADDED (2026-08-31, SFX refinement pass): looks up a short CC-licensed
    sound effect from the free Freesound.org API for one shot's keyword
    (see video_planning_agent.py's SFX_LINE_RULE for where the keyword
    comes from) and downloads its preview-quality mp3. Returns the local
    file path, or None if SFX is disabled, the keyword is missing, the
    search/download fails, or the per-run search cap is hit - every one of
    these is a silent, graceful degradation (that shot just has no SFX
    layer), matching the fail-open pattern _build_music_bed already uses
    for music tracks. Never raises - a real SFX layer is a quality
    enhancement, not something assembly should ever be blocked on.

    Uses an in-run cache keyed by the lowercased keyword, since many shots
    in the same script commonly share very similar SFX keywords (e.g.
    several "footsteps stone floor" shots) - this both saves API calls
    against the 2000/day budget and saves redundant downloads."""
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
    """ADDED (2026-08-31, SFX refinement pass): builds one AudioClip layer
    placing each shot's fetched SFX sound at that shot's start time within
    the timeline, matching shot boundaries computed from `durations` in
    the same order assemble.py already uses everywhere else (crossfade
    overlap between shots is a small, acceptable amount of timing slop for
    an ambient SFX hit - it doesn't need frame-accurate sync the way
    narration does). Returns None if no shot produced a usable SFX file
    (SFX disabled, all lookups failed, or no plan had SFX lines at all) -
    same optional-layer pattern as music."""
    if not FREESOUND_ENABLED:
        return None

    segments = []
    t = 0.0
    for keyword, dur in zip(sfx_keywords, durations):
        sfx_path = _fetch_shot_sfx(keyword, work_dir) if keyword else None
        if sfx_path:
            try:
                clip = AudioFileClip(sfx_path).volumex(SFX_VOLUME)
                # Trim an SFX hit that's longer than its shot so it doesn't
                # bleed audibly into the next shot's own sound.
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


def _chapter_time_bounds(total_duration):
    """Returns [(start, end, label, mood, filename), ...] for the chapters
    that fit inside total_duration, matching Rule 0's fixed timing spine
    in script_writing_agent.py exactly: Cold Open is a fixed 0-30s (or
    less, if narration itself is shorter than 30s), Problem/Stakes runs
    30s-25%, Rising Delivery 25%-50%, Midpoint Twist 50%-55% (a short band
    for the re-hook moment itself), Climax 55%-85%, Payoff 85%-100%."""
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
    """Builds one continuous music AudioClip spanning total_duration, made
    of each chapter's track trimmed/looped to fill its segment and
    crossfaded into the next at the boundary (MUSIC_CROSSFADE seconds of
    overlap with a fade on each side). Returns None if every track fails
    to download or MUSIC_ENABLED is False - music is an optional layer,
    never a hard dependency for assembly."""
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

    # ADDED (2026-08-31, SFX refinement pass): per-shot scripted SFX from
    # Freesound, distinct from native_sfx_path above - native_sfx_path is
    # WHATEVER incidental sound happened to be baked into the Agnes clip
    # itself (often faint/generic), while this is a real, specific sound
    # matched to what the shot's own production plan explicitly calls for
    # (see video_planning_agent.py's SFX_LINE_RULE). Both layers are kept
    # - they're complementary, not redundant.
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

    # See KEEP-ALIVE FIX (2026-08-30) docstring near _KEEPALIVE_STOP above.
    # Starts pinging /health every 5 min now, before any local rendering
    # begins, so the backend never crosses Render's ~15 min idle threshold
    # during the render (confirmed up to 56 min on video 4fc244de) and is
    # already warm for the small metadata calls this script still makes
    # to it (video fetch, narration download, final status PATCH).
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

    # CRF ENCODING (2026-08-30): replaces the old bitrate-budget calc - see
    # comment on VIDEO_CRF near the top of the file for why. CRF targets
    # constant visual quality directly; ffmpeg allocates however much
    # bitrate that actually needs, rather than us guessing a number and
    # accidentally starving 1080p footage of the bits it needs to look
    # like 1080p.
    print(
        f"Applying cinematic grade and merging mixed audio "
        f"(duration={target_duration:.1f}s, CRF={VIDEO_CRF}, no quality-compromising bitrate cap)..."
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
    print(f"Final file size: {final_size_mb:.1f}MB (CRF {VIDEO_CRF}, no size budget applied).")

    # DIRECT-TO-SUPABASE UPLOAD (2026-08-31): see note near the top of this
    # file. The large file (hundreds of MB at CRF 20) now goes straight
    # from this runner to Supabase Storage - Render never sees it. Only a
    # small JSON status update reaches Render afterward.
    print("Uploading finished video directly to Supabase Storage (bypassing Render for the large-file transfer)...")
    video_url = _upload_final_video_to_supabase(video_id, final_path)
    print(f"Uploaded to Supabase Storage: {video_url}")

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
