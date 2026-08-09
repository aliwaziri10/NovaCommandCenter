import os
import random
import time
import requests
import json
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.topic import Topic


# PROVIDER SWITCH (2026-08-10): Pollinations' free legacy text API
# (text.pollinations.ai) started returning HTTP 402 Payment Required with a
# deprecation notice - "The Pollinations legacy text API is being deprecated
# for authenticated users. Please migrate to https://enter.pollinations.ai" -
# confirmed live in Render logs. This is not a transient failure retries can
# fix; the free endpoint this agent depended on is being shut down. Switched
# to calling the Gemini API directly instead - same free-key approach already
# proven working in Marius's scripts/script_writing.py and TDP's
# generate_script.py. Requires the GEMINI_API_KEY secret (added to this repo
# on Render 2026-08-10, a separate key from Marius/TDP's so usage/quota
# don't compete across channels).
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

MAX_GENERATION_ATTEMPTS = 4
RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _call_gemini(prompt: str, system_prompt: str) -> str | None:
    """Same retry/backoff pattern as Marius's call_llm() - explicit 429
    handling, network-exception handling, and malformed-envelope handling
    all treated as retryable, escalating backoff between attempts, and a
    clean None return (never a silent empty success) if every attempt
    fails."""
    body = json.dumps({
        "contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
    }).encode()
    last_reason = None

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            resp = requests.post(
                GEMINI_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 15
            last_reason = f"{e.__class__.__name__}: {e}"
            print(f"Gemini network error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            wait = (attempt + 1) * 15
            last_reason = "HTTP 429 rate limited"
            print(f"Gemini rate limited, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if resp.status_code in (500, 502, 503, 504):
            wait = (attempt + 1) * 15
            last_reason = f"HTTP {resp.status_code}"
            print(f"Gemini transient error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS}): {resp.text[:200]}")
            time.sleep(wait)
            continue

        if resp.status_code != 200:
            last_reason = f"HTTP {resp.status_code} (non-retryable)"
            print(f"Gemini returned {last_reason}, attempt {attempt + 1}/"
                  f"{MAX_GENERATION_ATTEMPTS}: {resp.text[:200]}")
            continue

        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (requests.exceptions.JSONDecodeError, KeyError, IndexError) as e:
            wait = (attempt + 1) * 15
            last_reason = f"malformed response envelope ({e})"
            print(f"Gemini {last_reason}, waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

    print(f"Gemini still failing after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
    return None


def _parse_topics(raw: str):
    """Extract a list of topic dicts from a raw Gemini reply. Returns None
    (reject) if nothing usable was found - never silently returns []."""
    text = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        topics = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end <= start:
            return None
        try:
            topics = json.loads(text[start:end])
        except json.JSONDecodeError:
            return None

    if isinstance(topics, str):
        try:
            topics = json.loads(topics)
        except json.JSONDecodeError:
            return None

    if isinstance(topics, dict) and "title" in topics:
        topics = [topics]
    elif isinstance(topics, dict):
        found_list = None
        for value in topics.values():
            if isinstance(value, list) and value:
                found_list = value
                break
        topics = found_list

    if isinstance(topics, list) and topics and isinstance(topics[0], str):
        topics = [{"title": t} for t in topics]

    if not isinstance(topics, list) or not topics:
        return None

    return topics


def run_topic_research(db: Session, category: str = "History", count: int = 5):
    """PROVIDER SWITCH (2026-08-10): now uses Gemini directly instead of the
    deprecated Pollinations free text API - see module docstring above.

    FIX (2026-07-12, still relevant): existing topic titles are listed
    explicitly and the model is told not to repeat them, on top of the
    after-the-fact DB duplicate check below.
    """
    existing_titles = [t.title for t in db.query(Topic.title).all()]
    avoid_block = ""
    if existing_titles:
        avoid_block = (
            " Do NOT reuse or closely rephrase any of these existing titles: "
            + "; ".join(existing_titles[:50]) + "."
        )

    seed = random.randint(1, 10_000_000)

    system_prompt = (
        "You are a research assistant for an alternate-history YouTube channel. "
        "Respond with ONLY a valid JSON array. No markdown, no commentary, no code fences."
    )
    prompt = (
        f'Generate exactly {count} new, distinct video topic ideas in the category "{category}".'
        f'{avoid_block} '
        f'Format exactly: [{{"title": "...", "category": "{category}", '
        f'"trend_score": 0-100, "notes": "1-2 sentence pitch"}}] '
        f'(request id {seed})'
    )

    raw = _call_gemini(prompt, system_prompt)
    if raw is None:
        raise RuntimeError(
            f"Topic research failed for category '{category}' (Gemini returned "
            f"nothing usable after {MAX_GENERATION_ATTEMPTS} backoff-spaced attempts) - "
            f"no topics created, raising instead of silently reporting created=0 as a "
            f"success so this shows up as a failed task and gets retried."
        )

    topics = _parse_topics(raw)
    if topics is None:
        raise RuntimeError(
            f"Topic research for category '{category}' got a Gemini response but "
            f"could not parse a usable topic list out of it - raising instead of "
            f"reporting a false-success created=0. Raw response started with: "
            f"{raw[:200]!r}"
        )

    created = []
    skipped = []
    for t in topics:
        if not isinstance(t, dict):
            continue
        title = t.get("title", "Untitled")
        # Pre-check first (cheap, avoids most round trips), but the real
        # guarantee is the DB-level UNIQUE constraint on topics.title —
        # two concurrent/retrying runs can both pass this check before
        # either commits, so we still have to handle the race below.
        existing = db.query(Topic).filter(Topic.title == title).first()
        if existing:
            skipped.append(title)
            continue
        topic = Topic(
            title=title,
            category=t.get("category", category),
            trend_score=t.get("trend_score", 50),
            status="research",
            notes=t.get("notes", ""),
        )
        db.add(topic)
        try:
            db.commit()
            created.append(topic)
        except IntegrityError:
            # Another concurrent/retrying run inserted this exact title
            # first. Not a real error — treat it as a duplicate and move on.
            db.rollback()
            skipped.append(title)

    if not created and not skipped:
        raise RuntimeError(
            f"Topic research for category '{category}' returned a parsed topic list "
            f"but none of its entries were usable dicts with titles — raising instead "
            f"of reporting a false-success created=0."
        )

    return {
        "created": len(created),
        "titles": [t.title for t in created],
        "skipped_duplicates": skipped,
    }
