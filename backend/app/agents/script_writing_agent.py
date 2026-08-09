import os
import uuid
import re
import time
import requests
from sqlalchemy.orm import Session
from app.models.topic import Topic
from app.models.script import Script
from app.models import Task


def _latest_strategy_notes(db: Session) -> str | None:
    """Pulls the most recent completed strategy_research task's notes, if any.
    Returns None if that agent has never run - script generation works fine
    without it, this is a bonus signal when available."""
    task = (
        db.query(Task)
        .filter(Task.agent_name == "strategy_research", Task.status == "completed")
        .order_by(Task.created_at.desc())
        .first()
    )
    if not task or not task.payload:
        return None
    return (task.payload.get("result") or {}).get("notes")


# PROVIDER SWITCH (2026-08-10): Pollinations' free legacy text API
# (text.pollinations.ai) started returning HTTP 402 Payment Required with a
# deprecation notice - confirmed live in Render logs. Switched to calling the
# Gemini API directly instead, same free-key approach already proven working
# in Marius's scripts/script_writing.py and TDP's generate_script.py.
# Requires the GEMINI_API_KEY secret (added to this repo on Render
# 2026-08-10, a separate key from Marius/TDP's). This replaces the old
# _generate_part()/Pollinations retry logic; _looks_like_code_or_markup and
# _extract_script below are UNCHANGED and still apply to Gemini's raw text
# output for the same reason they applied to Pollinations' - guards against
# garbage/malformed output being spoken aloud by the TTS narrator.
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

# FIX (2026-08-03): the old fallback ("if len(text) > 100: return text") accepted
# ANY long response as valid script text, including malformed/broken output from
# the free Pollinations API - raw HTML error pages, JSON fragments, code, etc.
# That garbage was passing straight through to narration/TTS, which is why some
# videos start "speaking code/HTML" partway through (typically Part 2, when the
# free API degrades or errors under load). This now rejects anything that looks
# like code/markup/JSON before accepting it as narration-ready script text.
# Still relevant under Gemini - guards against any malformed/wrapped output.
_CODE_LIKE_MARKERS = (
    "<html", "<!doctype", "<div", "<span", "<body", "<script",
    "```", "function(", "function (", "=>", "SELECT *", "import ",
    "def ", "class ", "{\"", "[{", "</",
)


def _looks_like_code_or_markup(text: str) -> bool:
    lowered = text.lower()
    hits = sum(1 for marker in _CODE_LIKE_MARKERS if marker.lower() in lowered)
    if hits >= 2:
        return True
    symbol_count = sum(text.count(ch) for ch in "{}<>[]")
    if symbol_count > 5 and (symbol_count / max(len(text), 1)) > 0.01:
        return True
    return False


def _extract_script(raw: str) -> str | None:
    """Pull usable script text out of a raw AI reply, even if it's wrapped in JSON/reasoning.
    Returns None (reject) if what's left doesn't actually look like narration text."""
    text = raw.strip()
    match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if match:
        extracted = match.group(1)
        extracted = extracted.replace('\\n', '\n').replace('\\"', '"')
        if len(extracted) > 100 and not _looks_like_code_or_markup(extracted):
            return extracted
        return None
    if '"reasoning"' in text[:300] or text.startswith('{"role"'):
        return None
    if text.startswith('{"error"'):
        return None
    if len(text) > 100 and not _looks_like_code_or_markup(text):
        return text
    return None


MAX_GENERATION_ATTEMPTS = 4
RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _generate_part(prompt: str, system_prompt: str) -> str | None:
    """PROVIDER SWITCH (2026-08-10): now calls Gemini directly instead of
    Pollinations. Same retry/backoff shape as before."""
    body_text = f"{system_prompt}\n\n{prompt}"
    last_reason = None

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            response = requests.post(
                GEMINI_URL,
                json={"contents": [{"parts": [{"text": body_text}]}]},
                headers={"Content-Type": "application/json"},
                timeout=90,
            )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 15
            last_reason = f"{e.__class__.__name__}: {e}"
            print(f"Gemini network error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if response.status_code == 429:
            wait = (attempt + 1) * 15
            last_reason = "HTTP 429 rate limited"
            print(f"Gemini rate limited, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if response.status_code in (500, 502, 503, 504):
            wait = (attempt + 1) * 15
            last_reason = f"HTTP {response.status_code}"
            print(f"Gemini transient error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS}): {response.text[:200]}")
            time.sleep(wait)
            continue

        if response.status_code != 200:
            last_reason = f"HTTP {response.status_code} (non-retryable)"
            print(f"Gemini returned {last_reason}, attempt {attempt + 1}/"
                  f"{MAX_GENERATION_ATTEMPTS}: {response.text[:200]}")
            continue

        try:
            raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (requests.exceptions.JSONDecodeError, KeyError, IndexError) as e:
            wait = (attempt + 1) * 15
            last_reason = f"malformed response envelope ({e})"
            print(f"Gemini {last_reason}, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        extracted = _extract_script(raw_text.strip())
        if extracted:
            return extracted

        last_reason = "200 OK but response failed narration-text validation " \
                       "(empty, code/markup-like, or malformed envelope)"
        print(f"Gemini attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    print(f"Gemini still failing after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
    return None


def run_script_writing(db: Session, topic_id: str):
    """Generates a full video script in two parts (to avoid length cutoffs), using Gemini.
    Prompts are structured around retention-driven storytelling: a hook-first open,
    a curiosity beat roughly every 45 seconds of narration, a midpoint re-hook,
    a mid-video explicit tease of the biggest upcoming turning point, stacked
    micro-twists and a false-resolution beat, a callback to the opening image/question,
    two lightweight viewer-engagement prompts, and a payoff ending with a next-episode
    tease — written to be READ ALOUD by a human-sounding narrator, not to be skimmed
    as text.
    Skips generation entirely if a script for this topic already exists, to avoid duplicates.

    FAILURE FIX (2026-08-08): on a failed generation, this used to still save a
    Script row with a literal placeholder string as content. This now raises
    instead — matching the pattern video_planning_agent.py already uses for
    exactly this failure mode — so a failed generation goes through the normal
    Task/_failed_attempts retry path and no broken Script row is ever created
    or allowed downstream."""
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
        "vivid single moment over any kind of introduction. This opening image or claim "
        "must be concrete enough to return to later (rule 7, callback twist).\n\n"
        "1B. MACRO OPEN LOOP (critical): the hook must state or clearly imply ONE central "
        "'what if' question for the entire video — the big unresolved stakes the whole "
        "story hangs on. Do NOT fully answer it until the ending. Every scene should feel "
        "like it's circling that unanswered question, not just delivering isolated facts. "
        "This is the through-line that makes someone watch to the end.\n\n"
        "2. CURIOSITY BEATS / COUNTDOWN SPINE: structure the body of the video as a series "
        "of numbered or clearly sequential turning points (setup -> why it looked stable -> "
        "the actual twist/mechanism -> a concrete vivid consequence -> a bridge line into "
        "the next beat). Roughly every 45 seconds of spoken narration (approx. every "
        "100-120 words), introduce a new piece of information, a new question, or a small "
        "reveal that re-hooks attention (a 'micro open loop' — open it, then close it with "
        "a small payoff before opening the next). Never let a stretch run long without one, "
        "and never end a beat on a flat period — always bridge forward.\n\n"
        "2B. TWIST ESCALATION (do not use only one twist): give EACH turning point its own "
        "small reversal, not just the midpoint — something that looked like a win turns out "
        "to plant the next problem, or vice versa. Partway through the video, include one "
        "'false resolution' beat where something appears solved, then undercut it in the "
        "next beat. Structure the beats so scale escalates — personal, then local, then "
        "national, then civilizational/global stakes — so the video feels like it's "
        "building momentum even in a long runtime.\n\n"
        "3. MIDPOINT RE-HOOK (critical, do not skip): at roughly the halfway point of the "
        "ENTIRE script, insert a deliberate tone or stakes shift — a twist, a reversal of "
        "what the viewer thought was true, a sudden escalation, or a direct rhetorical "
        "question to the viewer ('But here's where it gets strange...'). This is the exact "
        "moment attention naturally drops, so treat it as a second hook, not just another "
        "beat. Immediately after this shift, explicitly tease the single biggest turning "
        "point still to come, by name or number, so the viewer has a concrete reason to "
        "keep watching through the slower middle (e.g. 'wait until you see what happens "
        "when...').\n\n"
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
        "6. VIEWER ENGAGEMENT PROMPTS (exactly two, lightweight, in-narration): weave in "
        "one short direct-address line early (within the first quarter of the video) that "
        "gives the viewer something cheap and fast to react to in the comments — a genuine "
        "either/or question tied to the topic, not a generic 'like and subscribe'. Weave in "
        "a second one around the midpoint re-hook (rule 3) that invites a real opinion or "
        "prediction about what happens next. Both must feel like a natural aside from the "
        "narrator, never like an ad break.\n\n"
        "7. CALLBACK TWIST + ENDING: close the macro open loop from rule 1B with a surprise, "
        "a broader implication, or a new question that lingers — never a flat summary. "
        "Reconnect explicitly to the concrete image or claim from the opening hook (rule 1) "
        "and reveal that it meant something different than it first appeared, now that the "
        "full story is known. End with a one-line tease of a related next-episode angle so "
        "the video sets up series continuity, without over-promising a specific title."
    )

    strategy_notes = _latest_strategy_notes(db)
    strategy_block = (
        f'\nCurrent niche trend notes (from recent competitor/self performance data, '
        f'use as light inspiration for title/hook framing, do not copy titles '
        f'directly):\n{strategy_notes}\n'
        if strategy_notes else ''
    )

    part1_prompt = (
        f'Write the FIRST HALF (roughly scenes 1-3) of a YouTube video script '
        f'for this topic:\nTitle: "{topic.title}"\nCategory: {topic.category}\n'
        f'Notes: {topic.notes}\n{strategy_block}\n'
        f'Start directly with [SCENE 1]. The very first lines must open with mystery, '
        f'conflict, or a striking consequence — hook the viewer before any explanation, '
        f'and clearly state or imply the ONE central "what if" question this whole video '
        f'hangs on (the macro open loop — do not resolve it yet). That opening image or '
        f'claim should be concrete enough to be worth returning to at the very end. Anchor '
        f'stakes in specific people, a nation, or a civilization the viewer can root for. '
        f'Structure this half as sequential turning points, each with its own small twist '
        f'(something that looks like a win quietly planting the next problem, or the '
        f'reverse) — never a flat recap of facts. Weave in a curiosity beat (a new '
        f'question or small reveal) roughly every 100-120 words, and let the emotional '
        f'tone swing between tension/dread and hope/ingenuity — never flat, never constant '
        f'dread. Within the first quarter of this half, include one short, natural direct-'
        f'address line asking the viewer a genuine either/or question tied to the topic — '
        f'not a generic "like and subscribe" ask. Write it to be spoken aloud by a human-'
        f'sounding narrator: vary sentence rhythm, use direct address and rhetorical '
        f'questions, favor concrete sensory detail over dry fact-listing. End this half at '
        f"a natural cliffhanger, at or near what should feel like the story's lowest point "
        f'or biggest reversal — do not conclude the video yet.'
    )
    part1 = _generate_part(part1_prompt, system_prompt)

    if not part1:
        raise RuntimeError(
            f"Script generation failed on part 1 for topic {topic_id} "
            f"(Gemini returned nothing usable after {MAX_GENERATION_ATTEMPTS} "
            f"backoff-spaced attempts) - no Script row created, will be retried by "
            f"the supervisor up to MAX_RETRIES instead of saving a placeholder that "
            f"would end up spoken aloud in the final video."
        )

    part2_prompt = (
        f'Continue this script directly from where it left off (write the '
        f'SECOND HALF, roughly scenes 4-6) for the topic "{topic.title}". '
        f'Here is the first half for context:\n\n{part1}\n\n'
        f'Continue the story, keep introducing a new question or small reveal '
        f'roughly every 100-120 words, and keep giving each turning point its own '
        f'small twist rather than relying on only one big reversal. IMPORTANT: at the '
        f'halfway point of this second half, insert a deliberate midpoint re-hook — a '
        f'twist, reversal, or sudden escalation that shifts tone and grabs attention '
        f'again, exactly when viewers typically start to drift. Immediately after that '
        f'shift, add a short direct-address line explicitly teasing the single biggest '
        f'turning point still to come, and a second short direct-address line inviting '
        f"the viewer's prediction or opinion on what happens next — both natural asides, "
        f'not ad breaks. Include one "false resolution" moment somewhere in this half '
        f'where something appears settled, then undercut it in the very next beat. Keep '
        f'the scale escalating — personal, then national, then civilizational stakes — '
        f'and keep swinging the emotional tone between tension/dread and hope/relief; '
        f'give the viewer real moments to root for before the next escalation. Keep '
        f'writing for the ear: varied sentence rhythm, direct address, sensory and '
        f'emotional detail, never flat or encyclopedic. Develop the consequences, bring '
        f'it to the present day, and close the central "what if" question from the '
        f'opening hook by explicitly returning to that opening image or claim and '
        f'revealing it means something different now that the full story is known — '
        f'end with a surprise or lingering implication, then one closing line teasing a '
        f'related next-episode angle. Do not repeat the first half — only write the new '
        f'continuation, starting with [SCENE 4].'
    )
    part2 = _generate_part(part2_prompt, system_prompt)

    if not part2:
        raise RuntimeError(
            f"Script generation failed on part 2 for topic {topic_id} "
            f"(Gemini returned nothing usable after {MAX_GENERATION_ATTEMPTS} "
            f"backoff-spaced attempts, part 1 succeeded). No Script row created — "
            f"will be retried by the supervisor up to MAX_RETRIES instead of "
            f"shipping a truncated script with a failure marker that would end up "
            f"spoken aloud in the final video."
        )

    content = part1 + "\n\n" + part2

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
