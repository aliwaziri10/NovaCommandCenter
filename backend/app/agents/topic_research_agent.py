import random
import time
import requests
import json
from urllib.parse import quote
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.topic import Topic


# RETRY-WITH-BACKOFF FIX (2026-08-10): same bug class already found and fixed
# in script_writing_agent.py's _generate_part() and in Marius/TDP's equivalent
# LLM-call functions - this function made a single Pollinations request with
# NO status_code check at all and NO retry. When Pollinations returned a
# transient 429/5xx, a rate-limited empty body, or a malformed/truncated JSON
# response, the existing fallback logic ("if not isinstance(topics, list):
# topics = []") silently swallowed it into an empty list instead of raising -
# so the task recorded status "completed" with created=0, titles=[],
# skipped_duplicates=[] and gave zero signal that anything had gone wrong.
# That is exactly the pattern observed in production: 7 consecutive runs on
# 2026-08-09 all returned created:0 with empty everything, while topics.title
# had not gained a new row since 2026-07-19 - the topic supply silently dried
# up and every downstream agent (script_writing, narration, assembly) starved
# with nothing to report as broken. This now explicitly validates
# response.status_code, retries retryable failures with escalating backoff,
# separates network exceptions from bad HTTP responses for clear logging, and
# - critically - raises instead of silently returning an empty result when no
# usable topics could be extracted after all attempts, so a real failure
# shows up as a failed task instead of a quietly "completed" no-op.
MAX_GENERATION_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _parse_topics(raw: str):
    """Extract a list of topic dicts from a raw Pollinations reply.
    Returns None (reject, triggers a retry) if nothing usable was found -
    never silently returns [] here, that decision is made once, explicitly,
    by the caller after all attempts are exhausted."""
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


def _fetch_topics(url: str, params: dict) -> list | None:
    last_reason = None

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=30)
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
            wait = (attempt + 1) * 10
            last_reason = f"{e.__class__.__name__}: {e}"
            print(f"Pollinations network error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS})...")
            time.sleep(wait)
            continue

        if response.status_code in RETRYABLE_STATUS_CODES:
            wait = (attempt + 1) * 10
            last_reason = f"HTTP {response.status_code}"
            print(f"Pollinations transient error ({last_reason}), waiting {wait}s before retry "
                  f"(attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS}): {response.text[:200]}")
            time.sleep(wait)
            continue

        if response.status_code != 200:
            last_reason = f"HTTP {response.status_code} (non-retryable)"
            print(f"Pollinations returned {last_reason}, attempt {attempt + 1}/"
                  f"{MAX_GENERATION_ATTEMPTS}: {response.text[:200]}")
            continue

        topics = _parse_topics(response.text)
        if topics:
            return topics

        last_reason = "200 OK but response failed topic-list validation " \
                       "(empty, malformed JSON, or no usable list found)"
        print(f"Pollinations attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    print(f"Pollinations still failing after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
    return None


def run_topic_research(db: Session, category: str = "History", count: int = 5):
    """Free version — uses Pollinations.ai instead of a paid API.

    FIX (2026-07-12): previously the exact same prompt was sent every run,
    which Pollinations appears to cache — every call was returning the
    identical single topic ("The Silk Road Reimagined...") which already
    existed, so `created` stayed at 0 run after run. Two changes fix this:
    1. A random seed is embedded in both the prompt text and the request
       params, so the request can't be served from cache.
    2. Existing topic titles are listed explicitly and the model is told
       not to repeat them, instead of relying only on the after-the-fact
       DB duplicate check.
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
    url = f"https://text.pollinations.ai/{quote(prompt)}"
    params = {
        "model": "openai",
        "system": system_prompt,
        "json": "true",
        "temperature": 0.9,
        "seed": seed,
    }

    topics = _fetch_topics(url, params)
    if topics is None:
        raise RuntimeError(
            f"Topic research failed for category '{category}' (Pollinations returned "
            f"nothing usable after {MAX_GENERATION_ATTEMPTS} backoff-spaced attempts) - "
            f"no topics created, raising instead of silently reporting created=0 as a "
            f"success so this shows up as a failed task and gets retried."
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
        # All parsed "topics" were unusable garbage (not dicts, or dicts with
        # no meaningful title) even though _fetch_topics returned a non-empty
        # list. This is a real failure, not a quiet no-op.
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
