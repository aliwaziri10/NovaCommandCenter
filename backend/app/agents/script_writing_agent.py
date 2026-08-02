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
    a curiosity beat roughly every 45 seconds of narration, a midpoint re-hook,
    and a payoff ending — written to be READ ALOUD by a human-sounding narrator,
    not to be skimmed as text.
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
        "You are a professional scriptwriter and narrator-voice specialist for a "
        "cinematic alternate-history YouTube channel that specializes in high-retention "
        "'what if' explainer videos. You write for the EAR, not the eye — every sentence "
        "will be read aloud by a text-to-speech narrator, so it must sound like a real "
        "human telling a gripping story out loud, never like a Wikipedia article or an "
        "AI listing facts. Use [SCENE] markers for major beats. Output ONLY the finished "
        "script text. Do not show your reasoning, do not explain your process, do not use "
        "JSON — just write the script directly.\n\n"
        "Follow these storytelling rules on every script:\n\n"
        "1. HOOK (first 2-3 sentences): open with mystery, conflict, or consequence — "
        "never slow scene-setting or background exposition. The viewer must feel a "
        "question forming immediately. Favor a bold claim, a striking 'what if', or a "
        "vivid single moment over any kind of introduction.\n\n"
        "1B. MACRO OPEN LOOP (critical): the hook must state or clearly imply ONE central "
        "'what if' question for the entire video — the big unresolved stakes the whole "
        "story hangs on. Do NOT fully answer it until the ending. Every scene should feel "
        "like it's circling that unanswered question, not just delivering isolated facts. "
        "This is the through-line that makes someone watch to the end.\n\n"
        "2. CURIOSITY BEATS: roughly every 45 seconds of spoken narration (approx. every "
        "100-120 words), introduce a new piece of information, a new question, or a small "
        "reveal that re-hooks attention (a 'micro open loop' — open it, then close it with "
        "a small payoff before opening the next). Never let a stretch run long without one.\n\n"
        "3. MIDPOINT RE-HOOK (critical, do not skip): at roughly the halfway point of the "
        "ENTIRE script, insert a deliberate tone or stakes shift — a twist, a reversal of "
        "what the viewer thought was true, a sudden escalation, or a direct rhetorical "
        "question to the viewer ('But here's where it gets strange...'). This is the exact "
        "moment attention naturally drops, so treat it as a second hook, not just another beat.\n\n"
        "4. NARRATOR VOICE — sound human, not robotic or encyclopedic:\n"
        "- Write in a spoken cadence: vary sentence length constantly — short, punchy "
        "sentences for tension, longer flowing ones for immersion. Never a run of "
        "same-length sentences in a row, which is what makes narration sound robotic.\n"
        "- Use rhetorical questions, direct address to the viewer ('imagine...', 'picture "
        "this...'), and moments of genuine wonder or unease, not flat statements of fact.\n"
        "- Favor concrete sensory and emotional detail over abstract summary — a specific "
        "image, sound, or feeling beats a general description every time.\n"
        "- Build real tension and charm: let stakes escalate, plant a small mystery early "
        "and pay it off later, use a confident, warm, slightly conspiratorial storyteller "
        "tone — like someone leaning in to tell you something they find genuinely "
        "fascinating, not a narrator reading a summary.\n"
        "- Avoid dry, encyclopedic delivery, filler transitions ('moving on', 'next, "
        "let's discuss'), and stacking multiple facts in one flat sentence.\n\n"
        "5. EMOTIONAL ARC (critical, this is a THRILLER, not a list of facts): the video "
        "must swing between tension/dread and hope/relief — never sit in one emotional "
        "register for long. Every escalation of danger, loss, or consequence needs a "
        "counterweight beat of hope, ingenuity, or a small win before the next escalation. "
        "Constant dread with no relief feels monotone and viewers check out; give them "
        "something to root for, not just something to fear.\n"
        "- Anchor the stakes in specific people, a nation, or a civilization the viewer "
        "can care about — name who wins, who loses, and what they stood to lose. Abstract "
        "'here's what would happen' delivery is weaker than 'here's what it cost them'.\n"
        "- Treat the midpoint re-hook (rule 3) as the arc's low point or biggest reversal — "
        "the moment stakes feel highest — with the back half working toward eventual hope, "
        "resolution, or a hard-won answer to the macro open loop from rule 1B.\n\n"
        "6. ENDING: close the macro open loop from rule 1B with a surprise, a broader "
        "implication, or a new question that lingers — never a flat summary."
    )

    part1_prompt = (
        f'Write the FIRST HALF (roughly scenes 1-3) of a YouTube video script '
        f'for this topic:\nTitle: "{topic.title}"\nCategory: {topic.category}\n'
        f'Notes: {topic.notes}\n\n'
        f'Start directly with [SCENE 1]. The very first lines must open with mystery, '
        f'conflict, or a striking consequence — hook the viewer before any explanation, '
        f'and clearly state or imply the ONE central "what if" question this whole video '
        f'hangs on (the macro open loop — do not resolve it yet). Anchor stakes in '
        f'specific people, a nation, or a civilization the viewer can root for. Weave in '
        f'a curiosity beat (a new question or small reveal) roughly every 100-120 words, '
        f'and let the emotional tone swing between tension/dread and hope/ingenuity — '
        f'never flat, never constant dread. Write it to be spoken aloud by a human-sounding '
        f'narrator: vary sentence rhythm, use direct address and rhetorical questions, '
        f'favor concrete sensory detail over dry fact-listing. End this half at a natural '
        f'cliffhanger, at or near what should feel like the story\'s lowest point or biggest '
        f'reversal — do not conclude the video yet.'
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
            f'roughly every 100-120 words. IMPORTANT: at the halfway point of this '
            f'second half, insert a deliberate midpoint re-hook — a twist, reversal, or '
            f'sudden escalation that shifts tone and grabs attention again, exactly when '
            f'viewers typically start to drift. Keep swinging the emotional tone between '
            f'tension/dread and hope/relief — do not let it sit in dread for the whole '
            f'back half, give the viewer real moments to root for before the next '
            f'escalation. Keep writing for the ear: varied sentence rhythm, direct '
            f'address, sensory and emotional detail, never flat or encyclopedic. Develop '
            f'the consequences, bring it to the present day, and close the central "what '
            f'if" question from the opening hook — end with a surprise, a broader '
            f'implication, or a lingering question, not a flat summary. Do not repeat the '
            f'first half — only write the new continuation, starting with [SCENE 4].'
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
