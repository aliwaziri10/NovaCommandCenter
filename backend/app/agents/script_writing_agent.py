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
#
# MODEL UPGRADE (2026-08-31, cinematic-direction pass): switched primary
# model from gemini-3.5-flash to gemini-2.5-pro. Flash is a speed/cost-
# tier model; this is explicitly a creative long-form writing task, where
# research and Google's own free-tier model-selection guidance both point
# to the Pro tier for coherent creative prose. Gemini 2.5 Pro is free-tier
# (no card required) with a real but low daily cap (order of tens of
# requests/day depending on current Google quotas) - at this pipeline's
# actual volume (2 calls per script, at most a handful of scripts/day),
# that cap is nowhere close to being hit. GEMINI_MODEL_FALLBACK exists so
# a 429/quota-exhausted response on the Pro model doesn't kill generation
# outright - it drops to Flash for that call only, rather than failing the
# whole script.
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL_PRIMARY = "gemini-2.5-pro"
GEMINI_MODEL_FALLBACK = "gemini-3.5-flash"


def _gemini_url(model: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"


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
    Pollinations. Same retry/backoff shape as before.

    MODEL UPGRADE (2026-08-31): tries GEMINI_MODEL_PRIMARY (2.5 Pro) for
    every attempt first; only drops to GEMINI_MODEL_FALLBACK (3.5 Flash)
    once the primary model itself returns a 429 (quota/rate limit) -
    a genuine "this model is unavailable right now" signal, not a quality
    problem - so the fallback preserves availability without silently
    downgrading quality on ordinary transient errors (which still retry
    on the primary model as before).
    """
    body_text = f"{system_prompt}\n\n{prompt}"
    last_reason = None
    current_model = GEMINI_MODEL_PRIMARY

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            response = requests.post(
                _gemini_url(current_model),
                json={"contents": [{"parts": [{"text": body_text}]}]},
                headers={"Content-Type": "application/json"},
                timeout=120,
            )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 15
            last_reason = f"{e.__class__.__name__}: {e}"
            print(f"Gemini ({current_model}) network error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if response.status_code == 429:
            last_reason = "HTTP 429 rate/quota limited"
            if current_model == GEMINI_MODEL_PRIMARY:
                print(f"Gemini {GEMINI_MODEL_PRIMARY} quota/rate limited - falling back to "
                      f"{GEMINI_MODEL_FALLBACK} for this call (attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS}).")
                current_model = GEMINI_MODEL_FALLBACK
                continue
            wait = (attempt + 1) * 15
            print(f"Gemini {current_model} also rate limited, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if response.status_code in (500, 502, 503, 504):
            wait = (attempt + 1) * 15
            last_reason = f"HTTP {response.status_code}"
            print(f"Gemini ({current_model}) transient error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS}): {response.text[:200]}")
            time.sleep(wait)
            continue

        if response.status_code != 200:
            last_reason = f"HTTP {response.status_code} (non-retryable)"
            print(f"Gemini ({current_model}) returned {last_reason}, attempt {attempt + 1}/"
                  f"{MAX_GENERATION_ATTEMPTS}: {response.text[:200]}")
            continue

        try:
            raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (requests.exceptions.JSONDecodeError, KeyError, IndexError) as e:
            wait = (attempt + 1) * 15
            last_reason = f"malformed response envelope ({e})"
            print(f"Gemini ({current_model}) {last_reason}, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        extracted = _extract_script(raw_text.strip())
        if extracted:
            return extracted

        last_reason = "200 OK but response failed narration-text validation " \
                       "(empty, code/markup-like, or malformed envelope)"
        print(f"Gemini ({current_model}) attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    print(f"Gemini still failing after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
    return None


# ADDED (2026-08-31, cinematic-direction pass): a second-pass revision call.
# Generates a full draft (part1+part2) exactly as before, then asks the
# model to critique and rewrite its OWN draft against a compact checklist
# before it's saved. This is a well-documented quality lever (draft-then-
# revise) that the pipeline previously had none of - first-draft output
# went straight to the database and then straight to narration.
# Deliberately best-effort: if this call fails for any reason, the
# unrevised draft is used instead (see run_script_writing) rather than
# blocking script generation entirely on a bonus quality pass.
REVISION_SYSTEM_PROMPT = (
    "You are a script editor reviewing a finished narration script for a cinematic "
    "alternate-history YouTube channel. You will be given a complete draft. Revise it "
    "and output the FULL revised script (same [CHAPTER] and [SCENE] markers, same overall "
    "length and structure) with these specific fixes applied wherever needed:\n\n"
    "1. Break up any run of same-length, same-rhythm sentences - vary sentence length "
    "aggressively, sentence to sentence.\n"
    "2. Remove any remaining generic AI-narrator phrasing (e.g. 'you are standing in', "
    "'picture yourself', 'in summary', 'to wrap up', 'little did they know', 'the rest, "
    "as they say, is history') and replace it with something specific to THIS story - "
    "never delete the beat, rewrite the line.\n"
    "3. Confirm at least two people are referred to by an actual name (real historical "
    "name where known, or a plausible period-appropriate invented name if the historical "
    "record doesn't name them) rather than only abstract labels like 'the general' or "
    "'the nation' throughout. If the draft never names anyone, add names now.\n"
    "4. Confirm the script clearly separates documented real history from the speculative "
    "'what if' branch with an explicit spoken seam (e.g. 'here's what we know actually "
    "happened...' before the pivot into 'but suppose, instead...'). If that seam is missing "
    "or blurry, add or sharpen it - never let a viewer be unsure which parts are real.\n"
    "5. If every beat of the story feels mechanically identical in rhythm and phrasing to a "
    "generic template (the same kind of line at the same kind of moment every time), "
    "rewrite so at least the cold open and the midpoint re-hook feel specific to this "
    "story's own content, not a reusable formula.\n\n"
    "Do not shorten the script, do not remove any [CHAPTER] or [SCENE] marker, do not add "
    "commentary about what you changed. Output ONLY the fully revised script text."
)


def _revise_script(full_draft: str) -> str:
    """Best-effort revision pass - see REVISION_SYSTEM_PROMPT above. Returns
    the revised text on success, or the original unrevised draft on any
    failure (network, bad response, validation failure) - a failed
    revision pass is never allowed to block or degrade script generation,
    since the unrevised draft is already a complete, valid script on its
    own."""
    prompt = f"Here is the complete draft script to revise:\n\n{full_draft}"
    try:
        revised = _generate_part(prompt, REVISION_SYSTEM_PROMPT)
    except Exception as e:
        print(f"Revision pass raised an exception, using unrevised draft instead: {type(e).__name__}: {e}")
        return full_draft

    if not revised or len(revised) < len(full_draft) * 0.6:
        print("Revision pass returned nothing usable or suspiciously short output - using unrevised draft instead.")
        return full_draft

    print("Revision pass succeeded - using revised script.")
    return revised


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

    [... history through 2026-08-19 items #1/#2/#3/#5/#9/#10/#12 unchanged - six-beat
    Curiosity Loop structure, cold open, chapter markers, steady fact density, peak
    moment at ~70% mark - see prior versions of this docstring for that history ...]

    CINEMATIC-DIRECTION PASS (2026-08-31): this update responds to a direct critique
    of the prompt's faults (formulaic identical macro-structure on every video,
    mandatory cold-open regardless of whether a story suits it, fixed-position
    engagement questions, zero worked examples, no narrator identity, no real-vs-
    speculative signposting, phrase-banning without replacements, no named
    characters/dialogue, no revision pass, and a speed-tier model used for a
    creative-writing task). Concrete changes:
    - Rule 0B (cold open) is now conditional, not mandatory - the model is told to
      use it only when the story's real climactic moment justifies opening out of
      order, and to open chronologically otherwise (still hooked per Rule 1).
    - Rule 6 (engagement questions) now says "wherever the story naturally earns it"
      instead of fixed structural positions.
    - New Rule 10: a consistent narrator identity/voice signature, so scripts read
      as distinctly Nova's voice rather than a generic AI-history-channel tone.
    - New Rule 11: explicit spoken seam separating documented real history from the
      speculative "what if" branch - a credibility/clarity requirement, not just style.
    - New Rule 12: at least two people must be given actual names (real where known,
      plausible invented names otherwise), with short attributed quoted dialogue
      lines permitted (narrator-voiced, not lip-synced - see video_planning_agent.py's
      matching "mid-speech" staging guidance for how these land visually).
    - WORKED EXAMPLES block added after the rules: concrete good/bad sentence pairs,
      replacing several phrase-only bans with actual demonstrated alternatives.
    - part2_prompt now receives part1's real word count (not just its raw text) so
      the "peak moment at ~70%" instruction can be grounded in a real number instead
      of the model guessing at relative position.
    - Model switched from gemini-3.5-flash to gemini-2.5-pro (free-tier, no cost -
      see GEMINI_MODEL_PRIMARY comment above) with automatic fallback to Flash only
      on an actual quota/rate-limit response, not on ordinary transient errors.
    - New best-effort revision pass (_revise_script) runs on the assembled full
      script before saving - see REVISION_SYSTEM_PROMPT above.

    FAILURE FIX (2026-08-08): on a failed generation, this used to still save a
    Script row with a literal placeholder string as content. This now raises
    instead — matching the pattern video_planning_agent.py already uses for
    exactly this failure mode — so a failed generation goes through the normal
    Task/_failed_attempts retry path and no broken Script row is ever created
    or allowed downstream.
    """
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
        "0. CURIOSITY LOOP MASTER STRUCTURE (video-wide shape — every script follows this "
        "SHAPE, but see Rule 0B: the SPECIFIC DEVICE used to open should vary story to "
        "story, not repeat identically every time): the whole script is built as a "
        "fixed six-beat Curiosity Loop that resolves gradually across the full runtime, "
        "never answering the core question early:\n"
        "- Beat 1 — OPENING HOOK (roughly the first 0-30 seconds of narration): the "
        "strongest possible hook for THIS specific story (see Rule 0B for how to choose "
        "its form).\n"
        "- Beat 2 — PROBLEM / STAKES SETUP (from the end of the opening hook to roughly "
        "the 25% mark): establish who/what/why and what's genuinely at stake.\n"
        "- Beat 3 — RISING DELIVERY (roughly 25% to the midpoint): escalating turning "
        "points, each with its own twist (see Rules 2 and 2B).\n"
        "- Beat 4 — MIDPOINT TWIST / RE-HOOK (roughly the halfway mark): the deliberate "
        "tone/stakes shift described in Rule 3 below.\n"
        "- Beat 5 — DELIVERY CONTINUES TO CLIMAX (from just past the midpoint to roughly "
        "the 85% mark): the story's turning points keep escalating toward their peak, "
        "reaching the single biggest moment of the story at roughly the 70% mark (see "
        "Rule 9).\n"
        "- Beat 6 — PAYOFF (the final ~15%): resolution that answers the macro open loop "
        "(Rule 1B) and, if a cold open was used, recontextualizes it (see Rule 0B and "
        "Rule 7).\n"
        "This six-beat loop maps directly onto a HOOK -> PROBLEM -> SOLUTION -> PAYOFF "
        "spine. Never let two beats blur into one flat, undifferentiated stretch — "
        "each beat should feel like a distinct movement of the story.\n\n"
        "0B. CHOOSE THE OPENING DEVICE PER STORY (do not default to the same device every "
        "time): every script must open with Rule 1's hook within the first few seconds, "
        "but HOW it opens should be chosen based on what actually makes THIS story land "
        "hardest, not a fixed formula applied identically to every topic:\n"
        "- If this story's single most dramatic moment happens later in the chronology "
        "and is strong enough that showing it first (out of order) would genuinely hook "
        "harder than a chronological start, use a cold open: state that moment as if it's "
        "happening now, then cut back with a real bridge line ('Rewind.' or equivalent) "
        "into the true chronological Problem/Stakes setup. That moment must be a genuine "
        "turning point that recurs in its proper place later — never invented.\n"
        "- If this story's real chronological beginning is ALREADY the stronger, more "
        "arresting opening (a striking first fact, an audacious decision, an immediate "
        "vivid consequence), open chronologically instead — do not force a flash-forward "
        "onto a story that doesn't need one.\n"
        "Pick whichever device genuinely serves THIS topic. Across many videos these "
        "should not all read as the identical device used the identical way — that "
        "sameness is itself a tell that undermines the channel, regardless of how good "
        "any single video is on its own.\n\n"
        "0C. CHAPTER MARKERS (bake in from generation, every script, no exceptions): "
        "insert a `[CHAPTER: <short curiosity-driven title>]` marker at the start of each "
        "of the six Curiosity Loop beats from Rule 0 — six chapter markers total per "
        "script (Opening Hook, Problem/Stakes, Rising Delivery, Midpoint Twist, Climax, "
        "Payoff). Write each title specific to the actual topic and phrased to create "
        "curiosity on its own, the way a real YouTube chapter title would — never a flat "
        "generic label like 'Background' or 'Part 2'; something like 'The Warning No One "
        "Believed' instead. These `[CHAPTER: ...]` markers are in addition to, and "
        "separate from, the existing `[SCENE]` markers — use both.\n\n"
        "1. HOOK (first 2-3 sentences): open with mystery, conflict, or consequence — "
        "never slow scene-setting or background exposition. The viewer must feel a "
        "question forming immediately. Favor a bold claim, a striking 'what if', or a "
        "vivid single moment over any kind of introduction. This opening image or claim "
        "must be concrete enough to return to later (rule 7, callback twist). NEVER open "
        "with a channel greeting, branded intro, or any variation of 'hey guys', 'welcome "
        "back', 'what's up everyone', or similar — the very first words spoken must be "
        "the hook itself, with zero preamble of any kind before it.\n\n"
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
        "- Use rhetorical questions and warm direct address to the viewer as the narrator's "
        "own voice ('here's the thing...', 'and this is where it gets strange...'), and "
        "moments of genuine wonder or unease, not flat statements of fact. Do NOT use the "
        "second-person 'you are standing in...', 'you find yourself...', or 'picture "
        "yourself in [place]...' you-are-there device — this is a well-known overused AI "
        "narration tell and must never appear. The narrator tells the story; the narrator "
        "does not place the viewer inside the scene as a character.\n"
        "- Favor concrete sensory and emotional detail over abstract summary — a specific "
        "image, sound, or feeling beats a general description every time.\n"
        "- Build real tension and charm: let stakes escalate, plant a small mystery early "
        "and pay it off later, use a confident, warm, slightly conspiratorial storyteller "
        "tone — like someone leaning in to tell you something they find genuinely "
        "fascinating, not a narrator reading a summary.\n"
        "- Avoid dry, encyclopedic delivery, filler transitions ('moving on', 'next, "
        "let's discuss'), and stacking multiple facts in one flat sentence.\n"
        "- PUNCTUATION IS PERFORMANCE (the narrator voice engine reads punctuation as "
        "timing, not just grammar): use an em-dash for a thought that cuts itself off or "
        "pivots — like this. Use an ellipsis for a genuine hesitation or dread beat... "
        "before landing the next line. Use short sentence fragments on their own for "
        "impact. Do not treat punctuation as decoration — it is the only pacing control "
        "available, so use it deliberately on every beat that needs a breath, a pause, or "
        "a jolt.\n\n"
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
        "6. VIEWER ENGAGEMENT PROMPTS (exactly two, lightweight, in-narration, placed "
        "WHEREVER the story naturally earns them — not at a fixed position just because a "
        "rule says so): weave in one short direct-address line at a point where the story "
        "itself raises a genuine either/or question tied to the topic, not a generic 'like "
        "and subscribe'. Weave in a second one around wherever the story's own tension "
        "peaks that invites a real opinion or prediction about what happens next. Both must "
        "feel like a natural aside from the narrator, prompted by what just happened in the "
        "STORY, never like an ad break bolted on at a scheduled timestamp.\n\n"
        "7. CALLBACK TWIST + ENDING: close the macro open loop from rule 1B with a surprise, "
        "a broader implication, or a new question that lingers — never a flat summary. If "
        "a cold open was used (Rule 0B), reconnect explicitly to that opening moment and "
        "reveal it meant something different than it first appeared, now that the full "
        "story is known; if the video opened chronologically instead, close by paying off "
        "the specific claim or image from the opening hook (Rule 1) in the same way. End "
        "with a one-line tease of a related next-episode angle so the video sets up series "
        "continuity, without over-promising a specific title. NEVER use 'in summary', 'to "
        "sum up', 'to wrap up', 'in conclusion', 'little did they know', or 'the rest, as "
        "they say, is history' anywhere in the script, especially the ending — the callback "
        "twist itself must do the work of closing the story; it must never be announced as "
        "a summary.\n\n"
        "8. SPECIFIC NUMBERS AND FACTS AT A STEADY RATE (do not front-load then go "
        "abstract): throughout the ENTIRE script — not just the opening — include a "
        "concrete, specific number, date, quantity, distance, percentage, or verifiable "
        "fact roughly every 100-150 words. These must be real and verifiable, never "
        "invented for dramatic effect. If you are not genuinely confident a specific "
        "figure is accurate, use a clearly-hedged real range or qualifier ('by some "
        "estimates', 'roughly', 'at least') rather than stating an invented-sounding exact "
        "number with false confidence — a vague-but-honest figure is better than a "
        "precise-sounding fabrication. Never let a long stretch run on vague language "
        "('a huge amount', 'many years', 'a massive army') when a specific figure is "
        "available and would land harder.\n\n"
        "9. PEAK MOMENT AT ~70% MARK (do not save the biggest moment for the very end): "
        "the single most exciting, impactful, or surprising moment of the ENTIRE story — "
        "the biggest 'wow' beat — should land at roughly the 70% mark of the full runtime, "
        "inside the CLIMAX beat (Beat 5 of Rule 0), not held back for the PAYOFF (Beat 6) "
        "at the very end. Placing it at ~70% keeps energy and retention high through the "
        "back stretch instead of asking viewers to sit through falling energy waiting for "
        "a payoff that never out-excites what already happened.\n\n"
        "10. NARRATOR IDENTITY (consistent across every script, never named or referenced "
        "on-screen or in narration itself — this shapes HOW the narrator writes and "
        "delivers, it is not a character the narrator plays or announces): the narrator is "
        "someone who has personally traced this story's paper trail — sharp, a little wry, "
        "genuinely obsessive about the specific overlooked detail that changes how the "
        "whole story reads. They don't perform generic wonder at the topic in the abstract; "
        "they get excited about ONE specific overlooked fact or document or decision and "
        "make the viewer feel like they're being let in on it. This tone should feel "
        "recognizably consistent script to script — never revert to a generic, "
        "interchangeable 'documentary narrator' voice that could belong to any channel.\n\n"
        "11. REAL VS. SPECULATIVE — EXPLICIT SEAM (critical, credibility requirement, not "
        "just style): this channel discloses to viewers that content is AI-generated, and "
        "the 'what if' premise means every script mixes real documented history with an "
        "invented hypothetical branch. The seam between the two must be explicit and "
        "spoken aloud, never blurred — a clear line like 'here's what we know actually "
        "happened...' immediately before pivoting into 'but suppose, instead...' or "
        "equivalent. A viewer must always be able to tell, in the moment, whether what "
        "they're hearing is documented fact or the speculative premise. Never let the "
        "narration state the speculative branch in the same flat declarative voice used "
        "for real historical facts — the invented material should always carry a marker "
        "of hypothetical framing (suppose, imagine if, in this scenario, had this "
        "happened instead) even while fully committing to telling it as a real story.\n\n"
        "12. NAMED PEOPLE + QUOTED DIALOGUE (do not leave every figure abstract): give at "
        "least two people in the story an actual name — use the real historical name where "
        "the record provides one; where the record doesn't name a specific individual, "
        "invent a plausible period- and culture-appropriate name rather than defaulting to "
        "'the general' or 'the villager' throughout. Include 2-4 short lines of direct "
        "quoted dialogue across the script, attributed to a named person (e.g. "
        "[Name] is said to have told [other person], \"...\" or a documented/plausible "
        "quote framed the same way) — kept SHORT (under ~20 words each) and natural to "
        "say aloud, since these will be voiced by the narrator as a quoted line, not "
        "lip-synced by a separate character. Use quoted dialogue at genuine turning "
        "points (a decision, a warning, a confrontation) where hearing the actual words "
        "lands harder than a paraphrase — not scattered randomly.\n\n"
        "WORKED EXAMPLES (study these, then write in this register — these are "
        "demonstrations of the rules above, not a formula to copy line for line):\n\n"
        "GOOD — varied rhythm, sensory detail, earned tension:\n"
        "\"The order took four minutes to reach the front line. Four minutes — that's all "
        "it was. But in those four minutes, three thousand men were already walking toward "
        "a river nobody had bothered to map.\"\n\n"
        "BAD (AI-generic, avoid this register entirely):\n"
        "\"This decision would have significant consequences for the outcome of the "
        "battle, as the soldiers were unaware of the danger that awaited them.\"\n"
        "Why the good version works: short punchy sentence, then a fragment for emphasis, "
        "then a longer sentence that lands the concrete image (a river, unmapped, three "
        "thousand men) instead of an abstract claim about 'significant consequences'.\n\n"
        "GOOD — named person + quoted dialogue at a turning point:\n"
        "\"General Okonkwo reportedly turned to his second before the retreat and said "
        "just five words: 'We don't have four minutes.'\"\n\n"
        "BAD (abstract, no name, no voice):\n"
        "\"The commander realized they were running out of time and had to make a "
        "difficult decision.\"\n\n"
        "GOOD — explicit real-vs-speculative seam:\n"
        "\"Here's what actually happened: the bridge held. Now suppose, instead, that one "
        "cable had snapped thirty seconds earlier.\"\n\n"
        "BAD (blurs fact and speculation with no seam):\n"
        "\"The bridge might have collapsed, changing everything that came after.\""
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
        f'hangs on (the macro open loop — do not resolve it yet). Decide for THIS specific '
        f'topic whether a cold open (flash-forward to a later dramatic moment) or a strong '
        f'chronological opening genuinely hooks harder — per Rule 0B, do not default to '
        f'the same device every time; pick whichever actually serves this story. That '
        f'opening image or claim should be concrete enough to be worth returning to at the '
        f'very end. Give at least two people in this story real names (real historical '
        f'names where known, plausible period-appropriate invented names otherwise) and '
        f'include at least one short (under ~20 words) attributed quoted line of dialogue '
        f'somewhere in this half, at a genuine turning point. Anchor stakes in specific '
        f'people, a nation, or a civilization the viewer can root for. Structure this half '
        f'as sequential turning points, each with its own small twist (something that looks '
        f'like a win quietly planting the next problem, or the reverse) — never a flat '
        f'recap of facts. Weave in a curiosity beat (a new question or small reveal) '
        f'roughly every 100-120 words, and let the emotional tone swing between '
        f'tension/dread and hope/ingenuity — never flat, never constant dread. Somewhere in '
        f'this half, wherever the story itself earns it, include one short, natural '
        f'direct-address line asking the viewer a genuine either/or question tied to the '
        f'topic — not a generic "like and subscribe" ask, and not forced in at a fixed '
        f'position if the story hasn\'t earned it yet. Write it to be spoken aloud by a '
        f'human-sounding narrator: vary sentence rhythm aggressively (short fragments, then '
        f'longer flowing sentences), use em-dashes and ellipses as real pacing/performance '
        f'marks (not just grammar), use direct address and rhetorical questions, favor '
        f'concrete sensory detail over dry fact-listing. Whenever narration crosses from '
        f'documented real history into the speculative "what if" branch, mark that seam '
        f'explicitly and out loud (Rule 11) — never blur the two. End this half at a '
        f"natural cliffhanger, at or near what should feel like the story's lowest point "
        f'or biggest reversal — do not conclude the video yet. '
        f'STRUCTURE THIS HALF AS THE FIRST THREE CURIOSITY LOOP BEATS, each opening with '
        f'its own `[CHAPTER: <curiosity-driven title>]` marker before its `[SCENE]` '
        f'marker: (1) OPENING HOOK — using whichever device (cold open or chronological) '
        f'you chose above; (2) PROBLEM/STAKES SETUP — establishing who/what/why and what '
        f'is genuinely at stake, with real names attached to real people; then (3) RISING '
        f'DELIVERY, the escalating turning points described above. If you used a cold '
        f'open, that moment must be a real turning point that recurs again, in its proper '
        f'chronological place, later in the full script — not an invented one-off. '
        f'Throughout this half, ground the story with a specific number, date, quantity, '
        f'distance, percentage, or verifiable fact roughly every 100-150 words — real '
        f'and verifiable only, hedged with a qualifier like "roughly" or "by some '
        f'estimates" rather than invented if you are not genuinely confident in an exact '
        f'figure, and never left vague when a real figure exists.'
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

    part1_word_count = len(part1.split())

    part2_prompt = (
        f'Continue this script directly from where it left off (write the '
        f'SECOND HALF, roughly scenes 4-6) for the topic "{topic.title}". '
        f'Here is the first half for context (it is exactly {part1_word_count} words of '
        f'narration - use this real number, not a guess, to judge relative position when '
        f'placing the ~70% peak-moment mark below):\n\n{part1}\n\n'
        f'Continue the story, keep introducing a new question or small reveal '
        f'roughly every 100-120 words, and keep giving each turning point its own '
        f'small twist rather than relying on only one big reversal. Stay consistent with '
        f'every named person, quoted line, and specific fact already established in the '
        f'first half above — do not introduce a conflicting name, number, or detail for '
        f'something already established. IMPORTANT: at the halfway point of this second '
        f'half, insert a deliberate midpoint re-hook — a twist, reversal, or sudden '
        f'escalation that shifts tone and grabs attention again, exactly when viewers '
        f'typically start to drift. Immediately after that shift, add a short '
        f'direct-address line explicitly teasing the single biggest turning point still '
        f'to come, and a second short direct-address line inviting the viewer\'s '
        f'prediction or opinion on what happens next — both natural asides, prompted by '
        f'the story itself, not ad breaks. Include one "false resolution" moment '
        f'somewhere in this half where something appears settled, then undercut it in the '
        f'very next beat. Keep the scale escalating — personal, then national, then '
        f'civilizational stakes — and keep swinging the emotional tone between '
        f'tension/dread and hope/relief; give the viewer real moments to root for before '
        f'the next escalation. Include at least one more short (under ~20 words) '
        f'attributed quoted line of dialogue somewhere in this half, at a genuine turning '
        f'point — from a named person, real or plausible. Keep writing for the ear: '
        f'varied sentence rhythm with em-dashes and ellipses used as real pacing marks, '
        f'direct address, sensory and emotional detail, never flat or encyclopedic. Keep '
        f'marking the seam explicitly (Rule 11) anywhere narration moves between '
        f'documented fact and the speculative branch. Develop the consequences, bring '
        f'it to the present day, and close the central "what if" question from the '
        f'opening hook. Do NOT use "in summary", "to sum up", "to wrap '
        f'up", "in conclusion", "little did they know", "the rest, as they say, is '
        f'history", or any similar summary-announcing / cliché-closing language anywhere '
        f'in this half, especially the ending — the callback twist itself must close the '
        f'story, never a stated summary. '
        f'STRUCTURE THIS HALF AS THE FINAL THREE CURIOSITY LOOP BEATS, each opening with '
        f'its own `[CHAPTER: <curiosity-driven title>]` marker before its `[SCENE]` '
        f'marker: (4) MIDPOINT TWIST — align this chapter with the midpoint re-hook '
        f'above; (5) CLIMAX — the delivery keeps escalating toward its highest point, '
        f'roughly up to the 85% mark of the full script, and the single most exciting or '
        f'impactful moment of the ENTIRE story must land inside THIS chapter, at roughly '
        f'the 70% mark of the full script (use the real {part1_word_count}-word count of '
        f'part one above plus this half\'s own length so far to judge that position '
        f'accurately) — not held back for the PAYOFF chapter; (6) '
        f'PAYOFF — the final stretch, roughly the last 15%, where the central "what if" '
        f'question is answered. In the PAYOFF chapter specifically: if part one used a '
        f'cold open, make sure the ending explicitly recontextualizes that opening '
        f'moment — the viewer should now understand it meant something different than it '
        f'first appeared, now that the full story, including how that moment actually '
        f'resolved chronologically, is known. If part one opened chronologically instead, '
        f'close by paying off the specific opening claim or image in the same spirit. '
        f'PAYOFF should feel like a satisfying, meaningful landing that resolves things — '
        f"it is not where the story's biggest excitement spike happens; that already "
        f'happened in CLIMAX. Do not repeat the first half — only write the new '
        f'continuation, starting with [CHAPTER: ...] then [SCENE 4]. '
        f'Keep grounding the story with a specific number, date, quantity, distance, '
        f'percentage, or verifiable fact roughly every 100-150 words throughout this '
        f'half too — spread evenly across the back half, hedge with a qualifier rather '
        f'than inventing an exact figure you are not confident in, and never clustered '
        f'only near the start.'
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

    draft = part1 + "\n\n" + part2
    content = _revise_script(draft)

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
