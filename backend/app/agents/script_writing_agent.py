import uuid
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models.topic import Topic
from app.models.script import Script


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
        "for major beats. Respond with ONLY the script text itself — no JSON, "
        "no explanations, no preamble, no notes about what you are doing."
    )
    prompt = (
        f'Write a full YouTube video script for this topic:\n'
        f'Title: "{topic.title}"\n'
        f'Category: {topic.category}\n'
        f'Notes: {topic.notes}\n\n'
        f'Start directly with [SCENE 1] and write the complete script.'
    )
    url = f"https://text.pollinations.ai/{quote(prompt)}"

    content = None
    last_error = None
    models_to_try = ["mistral", "llama", "openai"]

    for model in models_to_try:
        params = {"model": model, "system": system_prompt, "temperature": 0.85}
        try:
            response = requests.get(url, params=params, timeout=60)
            raw = response.text.strip()

            # Reject replies that leak internal reasoning/JSON scaffolding
            if raw.startswith('{"role"') or '"reasoning"' in raw[:200]:
                last_error = f"{model} returned internal reasoning instead of a script"
                continue

            if len(raw) > 150:
                content = raw
                break
            else:
                last_error = f"{model} returned too little content"
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
