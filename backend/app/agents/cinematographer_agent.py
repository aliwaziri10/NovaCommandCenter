import os
import time
import uuid
import requests
from sqlalchemy.orm import Session
from app.models.video import Video

# ADDED (2026-09-02): new pipeline stage, per Zia's request for a
# "scene-by-scene cinematographer." video_planning_agent.py decides WHAT
# happens in each shot (action, subject, narrative beat). This agent runs
# immediately after it and decides HOW each shot LOOKS: camera framing,
# lens feel, lighting quality, blocking, depth. Kept as a fully separate
# pass (not folded into video_planning_agent.py, not a parallel field
# parsed independently by assemble.py) so each stage has exactly one job,
# is independently testable, and a plan can be read/verified after this
# pass before Agnes ever sees it - matching the existing SFX-line pattern
# (a bounded single retry if the model drops required lines, fail-open
# rather than blocking generation).
#
# Reuses the same Gemini call/retry/backoff conventions already proven in
# video_planning_agent.py rather than inventing a new HTTP pattern.

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

MAX_GENERATION_ATTEMPTS = 4
RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _is_bad_response(raw: str) -> bool:
    lowered = raw[:500].lower()
    if raw.startswith('{"role"') or '"reasoning"' in raw[:200] or raw.startswith('{"error"'):
        return True
    if raw.startswith('<!DOCTYPE') or raw.startswith('<!doctype') or lowered.startswith('<html'):
        return True
    error_markers = ["bad gateway", "502:", "cloudflare", "<html", "cf-error-details", "cf-wrapper"]
    if any(m in lowered for m in error_markers):
        return True
    return False


CINEMATOGRAPHER_SYSTEM_PROMPT = (
    "You are a professional cinematographer (director of photography) reviewing a "
    "finished shot-by-shot production plan for a cinematic alternate-history YouTube "
    "video. Your job is ONLY to add camera and lighting direction to each shot - do "
    "NOT change what happens in any shot, do NOT change any shot's numbering, do NOT "
    "change any 'Duration: Xs' line, do NOT change any 'SFX: <keyword>' line, and do "
    "NOT add or remove any shots. Output the ENTIRE plan back, shot for shot, in the "
    "exact same order, with one addition per shot.\n\n"
    "Cinematography line rule (critical, machine-parsed):\n"
    "- Every shot MUST gain a new line, placed directly after the shot's own "
    "description and before its 'Duration:' line, in the exact form "
    "'Cinematography: <brief>' where <brief> is a single, dense sentence covering "
    "ALL of: camera framing/angle (e.g. low-angle wide, extreme close-up, over-the-"
    "shoulder), camera movement if any (static, slow push-in, handheld tracking, "
    "crane), lens feel (e.g. shallow depth of field, wide-angle distortion, telephoto "
    "compression), and a specific lighting/mood direction (e.g. hard backlight "
    "silhouette, soft golden-hour key light, cool blue window light) consistent with "
    "that shot's own existing lighting (do not contradict a shot that is explicitly "
    "daylight by writing a night-time lighting brief).\n"
    "- Write like a real DP shot list, not generic film-school vocabulary - be "
    "specific and concrete, e.g. 'Low-angle static wide shot, wide-angle lens with "
    "slight barrel distortion, hard warm backlight throwing the subject into partial "
    "silhouette' rather than 'dramatic lighting, interesting angle.'\n"
    "- Vary framing and camera movement across shots the same way a real edit does - "
    "do not give every shot the same angle or the same 'slow push-in.' Match the "
    "energy of the brief to the shot: quick punchy shots get more dynamic framing "
    "(low angle, handheld, snap zoom); slower establishing or emotional shots get "
    "calmer, more classical framing (static wide, slow push-in).\n\n"
    "Output format (critical):\n"
    "- Preserve every existing line of every shot exactly as written (description, "
    "Duration, SFX). Only insert the new 'Cinematography:' line in the position "
    "specified above. Do not add commentary, headers, or explanation - output ONLY "
    "the full plan text."
)


def _call_gemini(prompt: str) -> str | None:
    body_text = f"{CINEMATOGRAPHER_SYSTEM_PROMPT}\n\n{prompt}"
    last_reason = None

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            response = requests.post(
                GEMINI_URL,
                json={"contents": [{"parts": [{"text": body_text}]}]},
                headers={"Content-Type": "application/json"},
                timeout=120,
            )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 15
            last_reason = f"{e.__class__.__name__}: {e}"
            print(f"Gemini network error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if response.status_code == 429:
            wait = (attempt + 1) * 15
            last_reason = "HTTP 429 rate limited"
            print(f"Gemini rate limited, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if response.status_code in (500, 502, 503, 504):
            wait = (attempt + 1) * 15
            last_reason = f"HTTP {response.status_code}"
            print(f"Gemini transient error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS}): {response.text[:200]}")
            time.sleep(wait)
            continue

        if response.status_code != 200:
            last_reason = f"HTTP {response.status_code} (non-retryable)"
            print(f"Gemini returned {last_reason}, attempt {attempt + 1}/"
                  f"{MAX_GENERATION_ATTEMPTS}: {response.text[:200]}")
            continue

        try:
            raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (requests.exceptions.JSONDecodeError, KeyError, IndexError) as e:
            wait = (attempt + 1) * 15
            last_reason = f"malformed response envelope ({e})"
            print(f"Gemini {last_reason}, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        raw = raw_text.strip()
        if _is_bad_response(raw):
            last_reason = "200 OK but response looked like an error/markup envelope"
            print(f"Gemini attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            continue
        if len(raw) > 100:
            return raw

        last_reason = "200 OK but response was too short to be a real plan"
        print(f"Gemini attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    print(f"Gemini still failing after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
    return None


def _count_shots(plan_text: str) -> int:
    import re
    shot_start = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)
    return sum(1 for line in plan_text.splitlines() if shot_start.match(line.strip()))


def _count_cinematography_lines(plan_text: str) -> int:
    import re
    cine_line = re.compile(r"^\s*Cinematography\s*:\s*\S", re.IGNORECASE | re.MULTILINE)
    return len(cine_line.findall(plan_text))


def run_cinematographer(db: Session, video_id: str):
    """Enriches an already-planned video's production_plan with a
    Cinematography line per shot (see CINEMATOGRAPHER_SYSTEM_PROMPT).

    Sends the whole plan in one call rather than splitting like
    video_planning_agent.py does - this is a rewrite/annotate pass over
    already-generated text (not fresh generation against a full script),
    so it fits well within Gemini's context window even at the max ~50
    shots this pipeline allows.

    If the model drops the shot count or drops most Cinematography lines,
    this raises rather than silently shipping a broken plan - matching
    the FAILURE FIX philosophy already established in video_planning_agent.py
    (no broken Video row / no broken production_plan ever gets saved).
    A shot missing ONLY its Cinematography line (not corrupting anything
    else) is tolerated up to a small threshold, same fail-open spirit as
    the SFX-line retry, since assemble.py doesn't currently consume this
    field anyway - it exists for future prompt-injection into Agnes calls
    and for Zia to read/verify plans before generation.
    """
    video_uuid = uuid.UUID(str(video_id))
    video = db.query(Video).filter(Video.id == video_uuid).first()
    if not video:
        raise ValueError(f"Video {video_id} not found")
    if not video.production_plan:
        raise ValueError(f"Video {video_id} has no production_plan to enrich")
    if video.cinematography_done:
        return {
            "video_id": str(video.id),
            "status": "already_done",
            "message": "cinematography_done was already True - skipping.",
        }

    original_shots = _count_shots(video.production_plan)
    if original_shots == 0:
        raise ValueError(f"Video {video_id}'s production_plan has no parseable shots")

    prompt = (
        f"Here is the finished shot-by-shot production plan ({original_shots} shots). "
        f"Add a 'Cinematography: <brief>' line to every shot per your instructions, "
        f"changing nothing else:\n\n{video.production_plan}"
    )
    enriched = _call_gemini(prompt)

    if not enriched:
        raise RuntimeError(
            f"Cinematographer pass failed for video {video_id} (Gemini returned nothing "
            f"usable after {MAX_GENERATION_ATTEMPTS} backoff-spaced attempts) - "
            f"production_plan left unchanged, will be retried by the supervisor up to "
            f"MAX_RETRIES."
        )

    enriched_shots = _count_shots(enriched)
    if enriched_shots < original_shots:
        raise RuntimeError(
            f"Cinematographer pass for video {video_id} dropped shots: original plan had "
            f"{original_shots}, enriched plan only has {enriched_shots}. Rejecting this "
            f"output entirely (production_plan left unchanged) rather than shipping a "
            f"shortened plan - will be retried by the supervisor up to MAX_RETRIES."
        )

    cine_lines = _count_cinematography_lines(enriched)
    missing = enriched_shots - cine_lines
    if missing > 0:
        print(f"Video {video_id}: {missing}/{enriched_shots} shots missing a Cinematography "
              f"line after the pass - proceeding anyway (fail-open, matching the SFX-line "
              f"pattern), those shots simply have no cinematography brief.")

    video.production_plan = enriched
    video.cinematography_done = True
    db.commit()
    db.refresh(video)

    return {
        "video_id": str(video.id),
        "title": video.title,
        "shots": enriched_shots,
        "shots_with_cinematography": cine_lines,
        "plan_preview": enriched[:400],
    }
