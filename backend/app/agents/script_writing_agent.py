import requests
import json
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models.topic import Topic
from app.models.script import Script

def _call_pollinations(prompt: str, system_prompt: str) -> str:
    url = f"https://text.pollinations.ai/{quote(prompt)}"
    params = {"model": "openai", "system": system_prompt, "temperature": 0.85}
    response = requests.get(url, params=params, timeout=60)
    return response.text.strip()

def run_script_writing(db: Session, topic_id: str):
    """Generates a full video script in two parts to avoid truncation, using Pollinations.ai."""

    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise ValueError(f"Topic {topic_id} not found")

    system_prompt = (
        "You are a professional scriptwriter for a cinematic alternate-history "
        "YouTube channel. Write engaging, narrative-driven scripts with [SCENE] "
        "markers for major beats. Write plain script text only — no JSON, no "
        "commentary, no markdown."
    )

    part1_prompt = (
        f'Write the FIRST HALF of a YouTube video script (roughly scenes 1-3) '
        f'based on this topic:\nTitle: "{topic.title}"\nCategory: {topic.category}\n'
        f'Notes: {topic.notes}\n\nStart with a strong hook. End this half at a '
        f'natural cliffhanger point — do not conclude the video yet.'
    )
    part1 = _call_pollinations(part1_prompt, system_prompt)

    part2_prompt = (
        f'Continue this same script (write the SECOND HALF — roughly scenes 4-6) '
        f'for the topic "{topic.title}". Here is the first half for context:\n\n'
        f'{part1}\n\n'
        f'Continue directly from where it left off, develop the consequences, '
        f'bring it to the present day, and end with a strong closing line. '
        f'Do not repeat the first half — only write the new continuation.'
    )
    part2 = _call_pollinations(part2_prompt, system_prompt)

    full_content = part1.strip() + "\n\n" + part2.strip()

    script = Script(
        title=topic.title,
        content=full_content,
        status="draft",
        topic_id=topic.id,
    )
    db.add(script)
    db.commit()
    db.refresh(script)

    return {"script_id": str(script.id), "title": script.title, "status": script.status}
