import uuid
import re
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models.topic import Topic
from app.models.script import Script


def _extract_script(raw: str) -> str | None:
    """Pull usable script text out of a raw AI reply, even if it's wrapped in JSON/reasoning."""
    text = raw.strip()

    # If it's a JSON-wrapper with a "content" field, pull that out
    match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if match:
        extracted = match.group(1)
        extracted = extracted.replace('\\n', '\n').replace('\\"', '"')
        if len(extracted) > 150:
            return extracted

    # If it's a reasoning-wrapper (has "reasoning" key), reject entirely — not usable
    if '"reasoning"' in text[:300] or text.startswith('{"role"'):
        return None

    # If it looks like an error message from the service, reject
    if text.startswith('{"error"'):
        return None

    # Otherwise, if it's long enough plain text, treat it as the script itself
    if len(text) > 150:
        return text

    return None


def run_script_writing(db: Session, topic_id: str):
    """Free version — generates a full video script from a topic using Pollinations.ai."""
    topic_uuid = uuid.UUID(str(topic_id))
    topic = db.query(Topic).filter(Topic.id == topic_uuid).first()
    if not topic:
        raise ValueError(f"Topic {topic_id} not found")

    system_prompt = (
        "You are a professional scriptwriter for a cinematic alternate-history "
        "YouTube channel. Write engaging, narrative-driven scripts with a clear "
        "hook, escalating stakes, and a strong closing line. Use [SCENE] markers "
        "for major beats. Output ONLY the finished script text. Do not show your "
        "reasoning, do not think step by step out loud, do not explain your "
        "process, do not use JSON — just write the script directly."
    )
    prompt = (
        f'Write a full YouTube video script for this topic:\n'
        f'Title: "{topic.title}"\n'
        f'Category: {topic.category}\n'
        f'Notes: {topic.notes}\n\n'
        f'Start directly with [SCENE 1] and write the complete script now.'
    )
    url = f"https://text.pollinations.ai/{quote(prompt)}"

    content = None
    last_error = None
    models_to_try = ["openai", "openai", "openai"]  # retry same model, sometimes it behaves differently

    for model in models_to_try:
        params = {"model": model, "system": system_prompt, "temperature": 0.9}
        try:
            response = requests.get(url, params=params, timeout=60)
            raw = response.text.strip()
            extracted = _extract_script(raw)
            if extracted:
                content = extracted
                break
            else:
                last_error = f"{model} reply was not usable (reasoning, JSON, or error wrapper)"
        except Exception as e:
            last_error = f"{model} error: {e}"
            continue

    if not content:
        content = f"Script generation failed. Last issue: {last_error}"

    script = Script(
        title=topic.title,
        content=content,
        status="draft",
        topic_id=topic.id,
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    return {"script_id": str(script.id), "title": script.title, "status": script.status}
