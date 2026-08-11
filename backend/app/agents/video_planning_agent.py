import os
import re
import time
import uuid
import requests
from sqlalchemy.orm import Session
from app.models.script import Script
from app.models.video import Video

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

MAX_GENERATION_ATTEMPTS = 4
RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _strip_ad_footer(text: str) -> str:
    marker = "**Support Pollinations.AI:**"
    idx = text.find(marker)
    if idx != -1:
        return text[:idx].rstrip()
    idx2 = text.find("🌸 **Ad** 🌸")
    if idx2 != -1:
        return text[:idx2].rstrip()
    return text


def _looks_truncated(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return True
    return stripped[-1] not in ".!?\"'\u201d\u2019"


def _is_refusal(text: str) -> bool:
    refusal_markers = [
        "i'm sorry", "i am sorry", "i cannot continue", "i can't continue",
        "please provide", "could you provide", "i need the actual script",
        "i need the rest of the script",
    ]
    lowered = text[:250].lower()
    return any(m in lowered for m in refusal_markers)


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


NARRATION_WORDS_PER_SECOND = 2.5
TARGET_SECONDS_PER_SHOT = 5


def _estimate_target_shots(script_text: str) -> int:
    word_count = len(script_text.split())
    narration_seconds = word_count / NARRATION_WORDS_PER_SECOND
    shots = round(narration_seconds / TARGET_SECONDS_PER_SHOT)
    return max(3, shots)


SYSTEM_PROMPT = (
    "You are a professional video producer for a cinematic alternate-history "
    "YouTube channel. Break the given script into a clear shot-by-shot production "
    "plan: camera angles, visual style notes, and estimated duration per shot. "
    "Output ONLY the plan text directly. Do not show your reasoning, do not "
    "explain your process, do not use JSON — just write the plan.\n\n"
    "Formatting rule (critical, machine-parsed):\n"
    "- Every shot MUST start its own line with the literal word 'Shot' followed by "
    "a number, e.g. 'Shot 1:', 'Shot 2:'. Do NOT use the word 'Scene' anywhere as "
    "a line label — an automated parser looks for the word 'Shot' specifically and "
    "will silently drop any shot labeled 'Scene'.\n\n"
    "Shot count rule (critical):\n"
    "- The number of shots MUST scale with how much narration the section "
    "contains. You will be told approximately how many shots to produce for "
    "each section — treat that as a firm target, not a suggestion. Do not "
    "collapse a long section into just a handful of shots; if there is a lot "
    "of narration, there must be a correspondingly large number of shots "
    "covering it, at roughly 5 seconds of story-content per shot.\n\n"
    "Duration rules:\n"
    "- Every shot MUST end with a line in the exact form 'Duration: Xs' with a "
    "specific number of seconds.\n"
    "- Vary durations naturally like a real movie edit: quick 2-3s cuts for "
    "punchy reveals, list items, or fast-paced montage beats; longer 5-8s holds "
    "for establishing shots, wide landscapes, or emotional beats. Never give "
    "every shot the same duration — that reads as robotic pacing.\n\n"
    "Lighting rule (critical):\n"
    "- Unless the script explicitly describes a night scene, storm, or a scene "
    "that specifically calls for darkness, every shot MUST read as clearly, "
    "brightly lit — daylight, well-lit interiors, or warm golden-hour light. "
    "Do NOT default to moody, dark, shadowy, or storm-lit descriptions just "
    "for dramatic flavor — that is a common failure mode and it makes the "
    "final footage look muddy and hard to see. Reserve genuine darkness only "
    "for shots where the script itself is explicitly set at night or in bad "
    "weather.\n\n"
    "Visual rules:\n"
    "- Do NOT describe shots as close-ups of readable text, handwriting, "
    "newspapers, letters, books, or documents. AI video generation cannot render "
    "legible text and it will come out as garbled nonsense letters, which looks "
    "broken. If a document or paper needs to appear, either keep it out of focus "
    "in the background of a wider shot, or describe the person/object interacting "
    "with it rather than the text itself."
)


def _call_gemini(prompt: str) -> str | None:
    body_text = f"{SYSTEM_PROMPT}\n\n{prompt}"
    last_reason = None

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            response = requests.post(
                GEMINI_URL,
                json={"contents": [{"parts": [{"text": body_text}]}]},
                headers={"Content-Type": "application/json"},
                timeout=90,
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
            return _strip_ad_footer(raw)

        last_reason = "200 OK but response was too short to be a real plan"
        print(f"Gemini attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    print(f"Gemini still failing after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
    return None


def _continue_if_truncated(plan: str) -> str:
    continuation_attempts = 0
    while _looks_truncated(plan) and continuation_attempts < 3:
        continuation_attempts += 1
        continuation_prompt = (
            f"Here is a shot-by-shot video production plan that was cut off "
            f"mid-sentence. Continue it EXACTLY from where it left off, do not "
            f"repeat any earlier text, do not restart, just continue the plan "
            f"to completion including all remaining shots. Remember: every shot "
            f"line must start with the literal word 'Shot' followed by a number, "
            f"never 'Scene':\n\n{plan[-1500:]}"
        )
        cont_raw = _call_gemini(continuation_prompt)
        if not cont_raw:
            break
        if _is_refusal(cont_raw):
            break
        if len(cont_raw) > 20:
            plan = plan + "\n" + cont_raw
        else:
            break
    return plan


def run_video_planning(db: Session, script_id: str):
    """Generates a shot-by-shot breakdown from a script using Gemini (see
    PROVIDER SWITCH note - was Pollinations until 2026-08-11, switched for
    the same reason and in the same way as script_writing_agent.py and
    topic_research_agent.py: Pollinations' free text endpoint started failing
    ('returned nothing usable' after 3 retries), matching the failure history
    of every video_planning task back to 2026-07-24. Uses the same
    GEMINI_API_KEY secret already set on Render for the other two agents.

    FAILURE FIX (2026-07-23): on a failed generation, this used to still create a
    Video row with the literal error string saved as production_plan. Since the
    supervisor's video_planning stage skips any script that already has a Video
    row - regardless of whether its plan is real - that permanently stranded the
    script. Now this raises instead, so the failure goes through the same Task/
    _failed_attempts retry path every other agent already uses, and no broken
    Video row is ever created.

    FAILURE FIX (2026-07-24): the bad-response check rejects HTML/gateway-error
    pages as well as JSON-shaped error envelopes, so a malformed 200 OK response
    can't get saved into production_plan verbatim. Still applied under Gemini as
    a general malformed-output guard.

    FAILURE FIX (2026-07-25): if part 1 succeeded but part 2 failed, this used
    to still ship a Video row with a broken partial-plan marker. Now a part-2
    failure raises the same way a part-1 failure does, so the whole thing
    retries via the supervisor's normal retry path instead of quietly shipping
    a half-finished plan.

    FIX (2026-07-25): shot count is explicitly scaled to the word count of
    each script half via _estimate_target_shots(), instead of being left
    entirely up to the model's judgment.
    """
    script_uuid = uuid.UUID(str(script_id))
    script = db.query(Script).filter(Script.id == script_uuid).first()
    if not script:
        raise ValueError(f"Script {script_id} not found")

    full_content = script.content
    midpoint = len(full_content) // 2
    split_at = full_content.rfind("\n\n", 0, midpoint + 200)
    if split_at == -1 or split_at < midpoint - 1000:
        split_at = midpoint
    part1_script = full_content[:split_at]
    part2_script = full_content[split_at:]

    part1_target_shots = _estimate_target_shots(part1_script)
    part2_target_shots = _estimate_target_shots(part2_script)

    part1_prompt = (
        f'Create a shot-by-shot video production plan for the FIRST HALF of this '
        f'script:\n\n{part1_script}\n\n'
        f'This first half is approximately {len(part1_script.split())} words of '
        f'narration, so plan for approximately {part1_target_shots} shots to give '
        f'it full visual coverage — do not underscope this to a small handful of '
        f'shots. List each shot with camera direction, visual style, and estimated '
        f'duration. Vary shot lengths naturally (short punchy cuts vs. longer '
        f'holds) rather than using the same duration for every shot. Keep every '
        f'shot brightly and clearly lit unless the script explicitly calls for '
        f'night or bad weather. Avoid close-ups of readable text or documents. '
        f'Start directly with Shot 1. This is only the first half of the script — '
        f'end at a natural shot boundary, do not add a conclusion yet.'
    )
    part1 = _call_gemini(part1_prompt)

    if not part1:
        raise RuntimeError(
            f"Video planning failed on part 1 for script {script_id} "
            f"(Gemini returned nothing usable after {MAX_GENERATION_ATTEMPTS} "
            f"backoff-spaced attempts) - no Video row created, will be retried by "
            f"the supervisor up to MAX_RETRIES."
        )

    part1 = _continue_if_truncated(part1)

    part2_prompt = (
        f'Continue the shot-by-shot production plan directly from where it left '
        f'off, for the SECOND HALF of the same script:\n\n{part2_script}\n\n'
        f'This second half is approximately {len(part2_script.split())} words of '
        f'narration, so plan for approximately {part2_target_shots} shots to give '
        f'it full visual coverage — do not underscope this to a small handful of '
        f'shots. Here is the shot plan so far for context (do not repeat it, only '
        f'continue numbering from the next shot number):\n\n{part1[-1500:]}\n\n'
        f'Keep the same format: every shot starts with the literal word "Shot" '
        f'followed by a number (never "Scene"), and every shot ends with a '
        f'"Duration: Xs" line. Vary durations naturally. Keep every shot brightly '
        f'and clearly lit unless the script explicitly calls for night or bad '
        f'weather. Avoid close-ups of readable text or documents. Cover this '
        f'second half through to the end of the script.'
    )
    part2 = _call_gemini(part2_prompt)

    if not part2:
        raise RuntimeError(
            f"Video planning failed on part 2 for script {script_id} "
            f"(Gemini returned nothing usable after {MAX_GENERATION_ATTEMPTS} "
            f"backoff-spaced attempts, part 1 succeeded). No Video row created — "
            f"will be retried by the supervisor up to MAX_RETRIES instead of "
            f"shipping a truncated plan."
        )

    part2 = _continue_if_truncated(part2)
    plan = part1 + "\n" + part2

    video = Video(
        title=script.title,
        status="planned",
        views=0,
        topic_id=script.topic_id,
        script_id=script.id,
        production_plan=plan,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return {"video_id": str(video.id), "title": video.title, "status": video.status, "plan_preview": plan[:300]}
