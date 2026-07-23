import re
import uuid
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models.script import Script
from app.models.video import Video


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
    "Duration rules:\n"
    "- Every shot MUST end with a line in the exact form 'Duration: Xs' with a "
    "specific number of seconds.\n"
    "- Vary durations naturally like a real movie edit: quick 2-3s cuts for "
    "punchy reveals, list items, or fast-paced montage beats; longer 5-8s holds "
    "for establishing shots, wide landscapes, or emotional beats. Never give "
    "every shot the same duration — that reads as robotic pacing.\n\n"
    "Visual rules:\n"
    "- Do NOT describe shots as close-ups of readable text, handwriting, "
    "newspapers, letters, books, or documents. AI video generation cannot render "
    "legible text and it will come out as garbled nonsense letters, which looks "
    "broken. If a document or paper needs to appear, either keep it out of focus "
    "in the background of a wider shot, or describe the person/object interacting "
    "with it rather than the text itself."
)


def _query_pollinations(prompt: str) -> str | None:
    url = f"https://text.pollinations.ai/{quote(prompt)}"
    for _ in range(3):
        try:
            response = requests.get(
                url,
                params={"model": "openai", "system": SYSTEM_PROMPT, "temperature": 0.8},
                timeout=60,
            )
            raw = response.text.strip()
            if raw.startswith('{"role"') or '"reasoning"' in raw[:200] or raw.startswith('{"error"'):
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
        cont_url = f"https://text.pollinations.ai/{quote(continuation_prompt)}"
        try:
            cont_response = requests.get(
                cont_url,
                params={"model": "openai", "system": SYSTEM_PROMPT, "temperature": 0.8},
                timeout=60,
            )
            cont_raw = cont_response.text.strip()
            if cont_raw.startswith('{"role"') or '"reasoning"' in cont_raw[:200] or cont_raw.startswith('{"error"'):
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
    Video row is ever created."""
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

    part1_prompt = (
        f'Create a shot-by-shot video production plan for the FIRST HALF of this '
        f'script:\n\n{part1_script}\n\n'
        f'List each shot with camera direction, visual style, and estimated duration. '
        f'Vary shot lengths naturally (short punchy cuts vs. longer holds) rather than '
        f'using the same duration for every shot. Avoid close-ups of readable text or '
        f'documents. Start directly with Shot 1. This is only the first half of the '
        f'script — end at a natural shot boundary, do not add a conclusion yet.'
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
        f'Here is the shot plan so far for context (do not repeat it, only '
        f'continue numbering from the next shot number):\n\n{part1[-1500:]}\n\n'
        f'Keep the same format: every shot starts with the literal word "Shot" '
        f'followed by a number (never "Scene"), and every shot ends with a '
        f'"Duration: Xs" line. Vary durations naturally. Avoid close-ups of '
        f'readable text or documents. Cover this second half through to the end '
        f'of the script.'
    )
    part2 = _query_pollinations(part2_prompt)

    if part2:
        part2 = _continue_if_truncated(part2)
        plan = part1 + "\n" + part2
    else:
        plan = part1 + "\n[Second half of shot plan failed to generate — plan is incomplete]"

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
