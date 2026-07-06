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


def run_video_planning(db: Session, script_id: str):
    """Free version — generates a scene/shot breakdown from a script using Pollinations.ai."""
    script_uuid = uuid.UUID(str(script_id))
    script = db.query(Script).filter(Script.id == script_uuid).first()
    if not script:
        raise ValueError(f"Script {script_id} not found")

    system_prompt = (
        "You are a professional video producer for a cinematic alternate-history "
        "YouTube channel. Break the given script into a clear shot-by-shot production "
        "plan: camera angles, visual style notes, and estimated duration per scene. "
        "Output ONLY the plan text directly. Do not show your reasoning, do not "
        "explain your process, do not use JSON — just write the plan."
    )
    prompt = (
        f'Create a shot-by-shot video production plan for this script:\n\n'
        f'{script.content[:3000]}\n\n'
        f'List each scene with camera direction, visual style, and estimated duration. '
        f'Start directly with Scene 1.'
    )
    url = f"https://text.pollinations.ai/{quote(prompt)}"

    plan = None
    last_error = None

    for _ in range(3):
        params = {"model": "openai", "system": system_prompt, "temperature": 0.8}
        try:
            response = requests.get(url, params=params, timeout=60)
            raw = response.text.strip()

            if raw.startswith('{"role"') or '"reasoning"' in raw[:200] or raw.startswith('{"error"'):
                last_error = "AI reply was not usable (reasoning or error wrapper)"
                continue

            if len(raw) > 100:
                plan = _strip_ad_footer(raw)
                break
            else:
                last_error = "AI reply too short"
        except Exception as e:
            last_error = str(e)
            continue

    if not plan:
        plan = f"Video planning failed. Last issue: {last_error}"
    else:
        continuation_attempts = 0
        while _looks_truncated(plan) and continuation_attempts < 3:
            continuation_attempts += 1
            continuation_prompt = (
                f"Here is a shot-by-shot video production plan that was cut off "
                f"mid-sentence. Continue it EXACTLY from where it left off, do not "
                f"repeat any earlier text, do not restart, just continue the plan "
                f"to completion including all remaining scenes:\n\n{plan[-1500:]}"
            )
            cont_url = f"https://text.pollinations.ai/{quote(continuation_prompt)}"
            try:
                cont_response = requests.get(
                    cont_url,
                    params={"model": "openai", "system": system_prompt, "temperature": 0.8},
                    timeout=60,
                )
                cont_raw = cont_response.text.strip()
                if cont_raw.startswith('{"role"') or '"reasoning"' in cont_raw[:200] or cont_raw.startswith('{"error"'):
                    break
                cont_raw = _strip_ad_footer(cont_raw)
                if len(cont_raw) > 20:
                    plan = plan + "\n" + cont_raw
                else:
                    break
            except Exception:
                break

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
