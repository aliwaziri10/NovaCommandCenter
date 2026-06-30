import requests
import json
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models.topic import Topic


def run_topic_research(db: Session, category: str = "History", count: int = 5):
    """Free version — uses Pollinations.ai instead of a paid API."""
    system_prompt = (
        "You are a research assistant for an alternate-history YouTube channel. "
        "Respond with ONLY a valid JSON array. No markdown, no commentary, no code fences."
    )
    prompt = (
        f'Generate {count} new video topic ideas in the category "{category}". '
        f'Format exactly: [{{"title": "...", "category": "{category}", '
        f'"trend_score": 0-100, "notes": "1-2 sentence pitch"}}]'
    )
    url = f"https://text.pollinations.ai/{quote(prompt)}"
    params = {
        "model": "openai",
        "system": system_prompt,
        "json": "true",
        "temperature": 0.8,
    }
    response = requests.get(url, params=params, timeout=30)
    raw = response.text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        topics = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        topics = json.loads(raw[start:end])

    # If the AI wrapped the list inside quotes (a string), unwrap it
    if isinstance(topics, str):
        topics = json.loads(topics)

    # If the AI wrapped the list inside a dictionary/object, pull the list out
    if isinstance(topics, dict):
        found_list = None
        for value in topics.values():
            if isinstance(value, list):
                found_list = value
                break
        topics = found_list if found_list is not None else []

    # If items are plain strings instead of objects, convert them
    if isinstance(topics, list) and topics and isinstance(topics[0], str):
        topics = [
            {"title": t, "category": category, "trend_score": 50, "notes": ""}
            for t in topics
        ]

    if not isinstance(topics, list):
        topics = []

    created = []
    for t in topics:
        if not isinstance(t, dict):
            continue
        topic = Topic(
            title=t.get("title", "Untitled"),
            category=t.get("category", category),
            trend_score=t.get("trend_score", 50),
            status="research",
            notes=t.get("notes", ""),
        )
        db.add(topic)
        created.append(topic)
    db.commit()
    return {"created": len(created), "titles": [t.title for t in created]}
