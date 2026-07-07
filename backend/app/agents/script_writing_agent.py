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
    match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if match:
        extracted = match.group(1)
        extracted = extracted.replace('\\n', '\n').replace('\\"', '"')
        if len(extracted) > 100:
            return extracted
    if '"reasoning"' in text[:300] or text.startswith('{"role"'):
        return None
    if text.startswith('{"error"'):
        return None
    if len(text) > 100:
        return text
    return None


def _generate_part(prompt: str, system_prompt: str) -> str | None:
    url = f"https://text.pollinations.ai/{quote(prompt)}"
    for _ in range(3):
        try:
            params = {"model": "openai", "system": system_prompt, "temperature": 0.9}
            response = requests.get(url, params=params, timeout=60)
            extracted = _extract_script(response.text.strip())
            if extracted:
                return extracted
        except Exception:
            continue
    return None


def run_script_writing(db: Session, topic_id: str):
    """Generates a full video script in two parts (to avoid length cutoffs), using Pollinations.ai.
    Prompts are structured around retention-driven storytelling: a hook-first open,
    a curiosity beat roughly every 45 seconds of narration, and a payoff ending.
    Skips generation entirely if a script for this topic already exists, to avoid duplicates."""
    topic_uuid = uuid.UUID(str(topic_id))
    topic = db.query(Topic).filter(Topic.id == topic_uuid).first()
    if not topic:
        raise ValueError(f"Topic {topic_id} not found")

    existing = db.query(Script).filter(Script.topic_id == topic.id).first()
    if existing:
        return {
            "script_id": str(existing.id),
            "title": existing.title,
            "status": existing.status,
            "skipped_duplicate": True,
        }

    system_prompt = (
        "You are a professional scriptwriter for a cinematic alternate-history "
        "YouTube channel that specializes in high-retention 'what if' explainer videos. "
        "Use [SCENE] markers for major beats. Output ONLY the finished script text. "
        "Do not show your reasoning, do not explain your process, do not use JSON — "
        "just write the script directly.\n\n"
        "Follow these storytelling rules on every script:\n"
        "1. OPEN with mystery, conflict, or consequence in the first 2-3 sentences — "
        "never open with slow scene-setting or background exposition. The viewer must "
        "feel a question forming immediately.\n"
        "2. Roughly every 45 seconds of spoken narration (approx. every 100-120 words), "
        "introduce a new piece of information, a new question, or a small reveal that "
        "re-hooks attention — never let a stretch run long without a curiosity beat.\n"
        "3. Avoid dry, encyclopedic delivery. Write like a narrator building tension, "
        "not a textbook.\n"
        "4. END the video with a surprise, a broader implication, or a new question "
        "that lingers — never a flat summary."
    )

    part1_prompt = (
        f'Write the FIRST HALF (roughly scenes 1-3) of a YouTube video script '
        f'for this topic:\nTitle: "{topic.title}"\nCategory: {topic.category}\n'
        f'Notes: {topic.notes}\n\n'
        f'Start directly with [SCENE 1]. The very first lines must open with mystery, '
        f'conflict, or a striking consequence — hook the viewer before any explanation. '
        f'Weave in a curiosity beat (a new question or small reveal) roughly every '
        f'100-120 words. End this half at a natural cliffhanger — do not conclude '
        f'the video yet.'
    )
    part1 = _generate_part(part1_prompt, system_prompt)

    if not part1:
        content = "Script generation failed on part 1 — try running this task again."
    else:
        part2_prompt = (
            f'Continue this script directly from where it left off (write the '
            f'SECOND HALF, roughly scenes 4-6) for the topic "{topic.title}". '
            f'Here is the first half for context:\n\n{part1}\n\n'
            f'Continue the story, keep introducing a new question or small reveal '
            f'roughly every 100-120 words, develop the consequences, bring it to the '
            f'present day, and end with a surprise, a broader implication, or a '
            f'lingering question — not a flat summary. Do not repeat the first half '
            f'— only write the new continuation, starting with [SCENE 4].'
        )
        part2 = _generate_part(part2_prompt, system_prompt)
        content = part1 + "\n\n" + part2 if part2 else part1 + "\n\n[Part 2 generation failed — script is incomplete]"

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
