import uuid
import requests
import json
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
        "hook, escalating stakes, and a strong closing line. Respond with ONLY "
        "valid JSON. No markdown, no commentary, no code fences."
    )
    prompt = (
        f'Write a full YouTube video script based on this topic:\n'
        f'Title: "{topic.title}"\n'
        f'Category: {topic.category}\n'
        f'Notes: {topic.notes}\n\n'
        f'Format exactly: {{"title": "...", "content": "the full script, '
        f'with [SCENE] markers for major beats"}}'
    )
    url = f"https://text.pollinations.ai/{quote(prompt)}"
    params = {
        "model": "openai",
        "system": system_prompt,
        "json": "true",
        "temperature": 0.85,
    }
    response = requests.get(url, params=params, timeout=60)
    raw = response.text.strip().replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])

    if isinstance(data, str):
        data = json.loads(data)

    if isinstance(data, list) and data:
        data = data[0]

    if not isinstance(data, dict):
        data = {}

    content = data.get("content") or data.get("script") or "Script generation returned no content."

    script = Script(
        title=data.get("title", topic.title),
        content=content,
        status="draft",
        topic_id=topic.id,
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    return {"script_id": str(script.id), "title": script.title, "status": script.status}
