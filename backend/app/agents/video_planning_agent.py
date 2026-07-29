import os
import re
import uuid
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models.script import Script
from app.models.video import Video

# FIX (2026-07-29): Pollinations retired the old standalone text.pollinations.ai
# service and merged everything into one unified endpoint, gen.pollinations.ai.
# The old URL was returning nothing usable on every call, which is why every
# video-planning task for the last 6 days failed after 3 retries and no new
# Video row ever got created. This was silent - the supervisor just kept
# rescheduling the same doomed task forever instead of surfacing it as broken.
# The new endpoint may also expect an API key (see POLLINATIONS_API_KEY below).
# If a key turns out to be required, this will fail loudly with a clear error
# instead of silently retrying forever like the old bug did.
POLLINATIONS_TEXT_URL = "https://gen.pollinations.ai/text"
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY")  # optional - free tier may not need one


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
    """Catches non-plan responses: broken JSON envelopes AND error/gateway
    HTML pages (e.g. Cloudflare 502s from Pollinations' origin going down).
    FIX (2026-07-24): previously only checked for JSON-shaped errors, so a
    Cloudflare 502 HTML page (which is long and doesn't start with '{')
    sailed past the len(raw) > 100 check and got saved into production_plan
    as if it were a real shot plan. That HTML got repeated up to 6x across
    the 3 query retries + 3 continuation attempts, exactly matching what
    was found stored on video 77d9f6ee's production_plan field."""
    lowered = raw[:500].lower()
    if raw.startswith('{"role"') or '"reasoning"' in raw[:200] or raw.startswith('{"error"'):
        return True
    if raw.startswith('<!DOCTYPE') or raw.startswith('<!doctype') or lowered.startswith('<html'):
        return True
    error_markers = ["bad gateway", "502:", "cloudflare", "<html", "cf-error-details", "cf-wrapper"]
    if any(m in lowered for m in error_markers):
        return True
    return False


# Average narration pace and target clip length, used to scale the number of
# shots requested to the actual length of the script section. Without this,
# the model tended to produce roughly the same handful of shots regardless of
# whether the section was 200 words or 2000 words. Assembly then froze the
# last generated frame to stretch coverage across the full narration length,
# which is why long scripts "felt" like they turned into a static image with
# audio still playing underneath, even though nothing was technically cut off.
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


def _query_pollinations(prompt: str) -> str | None:
    url = f"{POLLINATIONS_TEXT_URL}/{quote(prompt)}"
    params = {"model": "openai", "system": SYSTEM_PROMPT, "temperature": 0.8}
    if POLLINATIONS_API_KEY:
        params["key"] = POLLINATIONS_API_KEY
    for _ in range(3):
        try:
            response = requests.get(url, params=params, timeout=60)
            raw = response.text.strip()
            if _is_bad_response(raw):
                continue
            if len(raw) > 100:
                return _strip_ad_footer(raw)
        except Exception:
            continue
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
        cont_url = f"{POLLINATIONS_TEXT_URL}/{quote(continuation_prompt)}"
        cont_params = {"model": "openai", "system": SYSTEM_PROMPT, "temperature": 0.8}
        if POLLINATIONS_API_KEY:
            cont_params["key"] = POLLINATIONS_API_KEY
        try:
            cont_response = requests.get(cont_url, params=cont_params, timeout=60)
            cont_raw = cont_response.text.strip()
            if _is_bad_response(cont_raw):
                break
            cont_raw = _strip_ad_footer(cont_raw)
            if _is_refusal(cont_raw):
                break
            if len(cont_raw) > 20:
                plan = plan + "\n" + cont_raw
            else:
                break
        except Exception:
            break
    return plan


def run_video_planning(db: Session, script_id: str):
    """Free version — generates a shot-by-shot breakdown from a script using Pollinations.ai.
    Splits the script into two halves (matching how script_writing_agent generates it)
    instead of truncating, so the full script gets shot-planned, not just the first ~6000 chars.

    FAILURE FIX (2026-07-23): on a failed generation, this used to still create a
    Video row with the literal error string saved as production_plan. Since the
    supervisor's video_planning stage skips any script that already has a Video
    row - regardless of whether its plan is real - that permanently stranded the
    script: no future retry ever ran, narration could still fire on it (it only
    needs script content, not production_plan), but video_clips/assembly never
    could (they require total_shots > 0, which a failure string parses to zero).
    Now this raises instead, so the failure goes through the same Task/
    _failed_attempts retry path every other agent already uses, and no broken
    Video row is ever created.

    FAILURE FIX (2026-07-24): _query_pollinations previously only rejected
    JSON-shaped error envelopes, not HTML error pages. A Cloudflare 502 page
    from Pollinations' origin passed the len(raw) > 100 check and got saved
    as production_plan verbatim. _is_bad_response() now also rejects HTML/
    gateway-error pages, so this same failure mode raises and retries instead
    of silently corrupting production_plan.

    FAILURE FIX (2026-07-25): if part 1 succeeded but part 2 failed, this used
    to still ship a Video row with a broken "[Second half of shot plan failed
    to generate — plan is incomplete]" marker tacked onto the end of a real
    plan. That marker text isn't a parseable shot, so generate_videos.py just
    silently produced clips for the (truncated) first half and the video came
    out cut off — exactly what happened to the "Alexander" video's plan,
    cutting off after 16 shots. Now a part-2 failure raises the same way a
    part-1 failure does, so the whole thing retries via the supervisor's
    normal retry path instead of quietly shipping a half-finished plan.

    FIX (2026-07-25): shot count is now explicitly scaled to the word count of
    each script half via _estimate_target_shots(), instead of being left
    entirely up to the model's judgment. This addresses long scripts getting
    the same small handful of shots as short ones, which forced assembly's
    frozen-last-frame safety net to stretch a handful of real clips across
    minutes of narration.

    FIX (2026-07-29): switched from the retired text.pollinations.ai endpoint
    to the current gen.pollinations.ai/text endpoint. The old endpoint was
    silently dead - every call failed, every retry failed, and the supervisor
    just kept rescheduling this task forever instead of surfacing it as
    permanently broken. This is why no new video had been planned in 6 days
    despite two scripts (cde377be, 1b31fbc5) sitting ready and waiting. Also
    added optional POLLINATIONS_API_KEY support, since the new unified
    endpoint's docs list a key parameter that the old free endpoint never
    required."""
    script_uuid = uuid.UUID(str(script_id))
    script = db.query(Script).filter(Script.id == script_uuid).first()
    if not script:
        raise ValueError(f"Script {script_id} not found")

    full_content = script.content
    midpoint = len(full_content) // 2
    # avoid splitting mid-sentence: snap to the nearest paragraph break near the midpoint
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
    part1 = _query_pollinations(part1_prompt)

    if not part1:
        raise RuntimeError(
            f"Video planning failed on part 1 for script {script_id} "
            f"(Pollinations returned nothing usable after 3 attempts) - no Video row created, "
            f"will be retried by the supervisor up to MAX_RETRIES."
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
    part2 = _query_pollinations(part2_prompt)

    if not part2:
        raise RuntimeError(
            f"Video planning failed on part 2 for script {script_id} "
            f"(Pollinations returned nothing usable after 3 attempts, part 1 "
            f"succeeded). No Video row created — will be retried by the "
            f"supervisor up to MAX_RETRIES instead of shipping a truncated plan."
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
