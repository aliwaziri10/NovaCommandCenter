import os
import re
import time
import uuid
import requests
from sqlalchemy.orm import Session
from app.models.script import Script
from app.models.video import Video

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"

MAX_GENERATION_ATTEMPTS = 4
RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _strip_ad_footer(text: str) -> str:
    marker = "**Support Pollinations.AI:**"
    idx = text.find(marker)
    if idx != -1:
        return text[:idx].rstrip()
    idx2 = text.find("🌸 **Ad** 🌸")
    if idx2 != -1:
        return text[:idx2].rstrip()
    return text


def _looks_truncated(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return True
    return stripped[-1] not in ".!?\"'\u201d\u2019"


def _is_refusal(text: str) -> bool:
    refusal_markers = [
        "i'm sorry", "i am sorry", "i cannot continue", "i can't continue",
        "please provide", "could you provide", "i need the actual script",
        "i need the rest of the script",
    ]
    lowered = text[:250].lower()
    return any(m in lowered for m in refusal_markers)


def _is_bad_response(raw: str) -> bool:
    lowered = raw[:500].lower()
    if raw.startswith('{"role"') or '"reasoning"' in raw[:200] or raw.startswith('{"error"'):
        return True
    if raw.startswith('<!DOCTYPE') or raw.startswith('<!doctype') or lowered.startswith('<html'):
        return True
    error_markers = ["bad gateway", "502:", "cloudflare", "<html", "cf-error-details", "cf-wrapper"]
    if any(m in lowered for m in error_markers):
        return True
    return False


NARRATION_WORDS_PER_SECOND = 2.5
TARGET_SECONDS_PER_SHOT = 5

MAX_SHOTS_PER_HALF = 25


def _estimate_target_shots(script_text: str) -> int:
    word_count = len(script_text.split())
    narration_seconds = word_count / NARRATION_WORDS_PER_SECOND
    shots = round(narration_seconds / TARGET_SECONDS_PER_SHOT)
    return max(3, min(shots, MAX_SHOTS_PER_HALF))


# SFX CUE FIELD (2026-08-31, refinement pass): the existing "Ambient sound
# rule" below already requires every shot's prose description to name an
# audible sound source (e.g. "the blacksmith's hammer rings against the
# anvil") - that requirement has been live since 2026-08-26, but nothing
# downstream has ever actually extracted and used it for real SFX. Rather
# than add a second, parallel field that could drift out of sync with the
# prose description, this adds a short, separate, MACHINE-PARSEABLE
# "SFX: <2-4 word sound keyword>" line to every shot, distilling whatever
# sound source the shot's own prose already names into a clean search term
# assemble.py can hand straight to the Freesound API (see assemble.py's
# _fetch_shot_sfx() for the consuming side). This keeps the prose
# description free-form/natural for Agnes's video prompt while giving
# assemble.py something reliable to parse, instead of trying to extract a
# search term from arbitrary sentence prose with regex/NLP guesswork.
SFX_LINE_RULE = (
    "\n\nSFX cue line (critical, machine-parsed, in addition to the ambient "
    "sound rule above):\n"
    "- Every shot MUST end with a second line, after the Duration line, in the "
    "exact form 'SFX: <keyword>' where <keyword> is a short 2-4 word search "
    "term for the SPECIFIC sound this shot's own description already names "
    "(e.g. if the shot describes 'the blacksmith's hammer rings against the "
    "anvil', the SFX line should read 'SFX: blacksmith hammer anvil'). This "
    "keyword will be used to search a real sound-effects library, so it must "
    "describe a concrete, literal, searchable sound - never an emotion, mood, "
    "or abstract word. If a shot's description doesn't clearly name one "
    "specific sound, use the single most obvious ambient sound implied by the "
    "setting (e.g. 'wind', 'crowd murmur', 'footsteps stone floor')."
)


def _parse_shots(production_plan: str):
    """ADDED (2026-08-31): lightweight shot splitter used only to validate
    that every shot in a freshly generated plan actually carries an SFX
    line before this plan is accepted - keeps a malformed/missing-SFX plan
    from silently reaching assemble.py with gaps. Mirrors the SHOT_START
    matching convention assemble.py itself already uses, so the two stay
    in agreement about what counts as a shot boundary."""
    shot_start = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)
    blocks = []
    current = []
    for line in production_plan.splitlines():
        if shot_start.match(line.strip()):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _count_missing_sfx(production_plan: str) -> int:
    shots = _parse_shots(production_plan)
    sfx_line = re.compile(r"^\s*SFX\s*:\s*\S", re.IGNORECASE | re.MULTILINE)
    missing = sum(1 for shot in shots if not sfx_line.search(shot))
    return missing


SYSTEM_PROMPT = (
    "You are a professional video producer for a cinematic alternate-history "
    "YouTube channel. Break the given script into a clear shot-by-shot production "
    "plan: camera angles, visual style notes, and estimated duration per shot. "
    "Output ONLY the plan text directly. Do not show your reasoning, do not "
    "explain your process, do not use JSON — just write the plan.\n\n"
    "Formatting rule (critical, machine-parsed):\n"
    "- Every shot MUST start its own line with the literal word 'Shot' followed by "
    "a number, e.g. 'Shot 1:', 'Shot 2:'. Do NOT use the word 'Scene' anywhere as "
    "a line label — an automated parser looks for the word 'Shot' specifically and "
    "will silently drop any shot labeled 'Scene'.\n\n"
    "Shot count rule (critical):\n"
    "- The number of shots MUST scale with how much narration the section "
    "contains, UP TO the target given to you. You will be told approximately "
    "how many shots to produce for each section — treat that as a firm cap, "
    "not just a floor. Do not collapse a long section into just a handful of "
    "shots, but do NOT exceed the given target either — if there is a lot of "
    "narration, let individual shots run longer (use the fuller end of the "
    "5-8s duration range) rather than adding more shots than the target "
    "allows.\n\n"
    "Duration rules:\n"
    "- Every shot MUST end with a line in the exact form 'Duration: Xs' with a "
    "specific number of seconds.\n"
    "- Vary durations naturally like a real movie edit: quick 2-3s cuts for "
    "punchy reveals, list items, or fast-paced montage beats; longer 5-8s holds "
    "for establishing shots, wide landscapes, or emotional beats. Never give "
    "every shot the same duration — that reads as robotic pacing.\n\n"
    "Lighting rule (critical):\n"
    "- Unless the script explicitly describes a night scene, storm, or a scene "
    "that specifically calls for darkness, every shot MUST read as clearly, "
    "brightly lit — daylight, well-lit interiors, or warm golden-hour light. "
    "Do NOT default to moody, dark, shadowy, or storm-lit descriptions just "
    "for dramatic flavor — that is a common failure mode and it makes the "
    "final footage look muddy and hard to see. Reserve genuine darkness only "
    "for shots where the script itself is explicitly set at night or in bad "
    "weather.\n\n"
    "Visual rules:\n"
    "- Do NOT describe shots as close-ups of readable text, handwriting, "
    "newspapers, letters, books, or documents. AI video generation cannot render "
    "legible text and it will come out as garbled nonsense letters, which looks "
    "broken. If a document or paper needs to appear, either keep it out of focus "
    "in the background of a wider shot, or describe the person/object interacting "
    "with it rather than the text itself.\n\n"
    "Protagonist visibility rule (critical):\n"
    "- Do NOT put the protagonist on-screen in every shot, and do NOT default "
    "to opening and closing every shot on the protagonist. Across the full "
    "plan, only roughly 35% of shots should feature the protagonist directly "
    "on-screen. The remaining ~65% should be shots that don't need the "
    "protagonist visible at all: wide establishing shots, environment and "
    "setting details, objects, hands, other people, POV shots, and reaction "
    "or cutaway shots that still carry the narration forward. Constant "
    "protagonist presence reads as repetitive and staged - vary who and what "
    "is actually on screen.\n\n"
    "Ambient sound rule (critical):\n"
    "- Every shot's description must include one concrete, audible sound "
    "source woven naturally into the sentence itself (not a separate line) - "
    "e.g. 'the blacksmith's hammer rings against the anvil' or 'wind rattles "
    "the shutters' rather than a purely silent visual description. The video "
    "generation model has nothing to render as sound unless the shot text "
    "itself describes something making noise, and generated clips are "
    "currently coming out silent - give every shot a real audible source: "
    "footsteps, wind, fire, tools, crowd murmur, hooves, waves, machinery, "
    "etc., whatever actually fits the scene."
) + SFX_LINE_RULE


def _call_gemini(prompt: str) -> str | None:
    body_text = f"{SYSTEM_PROMPT}\n\n{prompt}"
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

        raw = raw_text.strip()
        if _is_bad_response(raw):
            last_reason = "200 OK but response looked like an error/markup envelope"
            print(f"Gemini attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")
            continue
        if len(raw) > 100:
            return _strip_ad_footer(raw)

        last_reason = "200 OK but response was too short to be a real plan"
        print(f"Gemini attempt {attempt + 1}/{MAX_GENERATION_ATTEMPTS} failed - {last_reason}")

    print(f"Gemini still failing after {MAX_GENERATION_ATTEMPTS} attempts. Last reason: {last_reason}")
    return None


def _continue_if_truncated(plan: str) -> str:
    continuation_attempts = 0
    while _looks_truncated(plan) and continuation_attempts < 3:
        continuation_attempts += 1
        continuation_prompt = (
            f"Here is a shot-by-shot video production plan that was cut off "
            f"mid-sentence. Continue it EXACTLY from where it left off, do not "
            f"repeat any earlier text, do not restart, just continue the plan "
            f"to completion including all remaining shots. Remember: every shot "
            f"line must start with the literal word 'Shot' followed by a number, "
            f"never 'Scene', and every shot must end with both a 'Duration: Xs' "
            f"line and an 'SFX: <keyword>' line:\n\n{plan[-1500:]}"
        )
        cont_raw = _call_gemini(continuation_prompt)
        if not cont_raw:
            break
        if _is_refusal(cont_raw):
            break
        if len(cont_raw) > 20:
            plan = plan + "\n" + cont_raw
        else:
            break
    return plan


def _retry_missing_sfx(plan: str, script_text: str, target_shots: int, half_label: str) -> str:
    """ADDED (2026-08-31): one bounded retry if the model produced shots
    without an SFX line - rather than silently shipping a plan with gaps
    (which would just mean those specific shots get no SFX layer later in
    assemble.py, a soft/invisible degradation), ask once for a corrected
    version. If the retry doesn't fully fix it either, the plan is still
    accepted as-is - a partially-covered SFX layer is a real but minor
    quality gap, not worth blocking video generation over, matching the
    fail-open philosophy already used for music/native-audio elsewhere in
    this pipeline."""
    missing = _count_missing_sfx(plan)
    if missing == 0:
        return plan
    print(f"{half_label}: {missing} shot(s) missing an 'SFX:' line - requesting one corrected pass.")
    fix_prompt = (
        f"Here is a shot-by-shot production plan for this script:\n\n{script_text}\n\n"
        f"Re-output the FULL plan below, unchanged except that every single shot "
        f"must end with an 'SFX: <keyword>' line as well as its 'Duration: Xs' "
        f"line - some shots in the draft below are missing the SFX line. Keep "
        f"everything else (shot numbering, descriptions, durations) exactly as "
        f"written, just add the missing SFX lines:\n\n{plan}"
    )
    fixed = _call_gemini(fix_prompt)
    if fixed and len(fixed) > len(plan) * 0.6:
        still_missing = _count_missing_sfx(fixed)
        print(f"{half_label}: after retry, {still_missing} shot(s) still missing SFX (was {missing}).")
        return fixed
    print(f"{half_label}: SFX-line retry didn't produce usable output - keeping original plan "
          f"(some shots will simply have no SFX layer at assembly time).")
    return plan


def run_video_planning(db: Session, script_id: str):
    """Generates a shot-by-shot breakdown from a script using Gemini (see
    PROVIDER SWITCH note - was Pollinations until 2026-08-11, switched for
    the same reason and in the same way as script_writing_agent.py and
    topic_research_agent.py: Pollinations' free text endpoint started failing
    ('returned nothing usable' after 3 retries), matching the failure history
    of every video_planning task back to 2026-07-24. Uses the same
    GEMINI_API_KEY secret already set on Render for the other two agents.

    FAILURE FIX (2026-07-23): on a failed generation, this used to still create a
    Video row with the literal error string saved as production_plan. Since the
    supervisor's video_planning stage skips any script that already has a Video
    row - regardless of whether its plan is real - that permanently stranded the
    script. Now this raises instead, so the failure goes through the same Task/
    _failed_attempts retry path every other agent already uses, and no broken
    Video row is ever created.

    FAILURE FIX (2026-07-24): the bad-response check rejects HTML/gateway-error
    pages as well as JSON-shaped error envelopes, so a malformed 200 OK response
    can't get saved into production_plan verbatim. Still applied under Gemini as
    a general malformed-output guard.

    FAILURE FIX (2026-07-25): if part 1 succeeded but part 2 failed, this used
    to still ship a Video row with a broken partial-plan marker. Now a part-2
    failure raises the same way a part-1 failure does, so the whole thing
    retries via the supervisor's normal retry path instead of quietly shipping
    a half-finished plan.

    FIX (2026-07-25): shot count is explicitly scaled to the word count of
    each script half via _estimate_target_shots(), instead of being left
    entirely up to the model's judgment.

    CAP ADDED (2026-08-11): _estimate_target_shots() now caps at
    MAX_SHOTS_PER_HALF (25/half, 50 total) - see comment there. The first
    video planned under the Gemini switch came out to 200 total shots with no
    prior cap, which at generate_videos.py's clip-generation pace would have
    taken roughly 10 hours for one video alone.

    UPDATED (2026-08-26): Zia flagged the protagonist appearing in nearly
    every shot (opening and closing on them by default) and generated clips
    coming out with no audible sound effects at all (music-only). Added two
    rules to SYSTEM_PROMPT (applies to both part1 and part2 calls, since
    SYSTEM_PROMPT is prepended to every _call_gemini() call): a protagonist
    visibility cap (~35% of shots) so most shots read as cutaways/environment/
    other people instead of constant protagonist presence, and an ambient
    sound rule requiring each shot's own description to name something
    audible happening in-frame - Agnes has nothing to render as sound unless
    the shot text itself describes a sound source, so this is upstream of
    assemble.py's native-audio extraction, not a replacement for it.

    SFX REFINEMENT PASS (2026-08-31): the 2026-08-26 ambient-sound rule made
    every shot's PROSE name a sound source, but nothing downstream ever
    actually turned that into a real, mixed-in sound effect - assemble.py's
    only audio layers were narration, whatever incidental native audio
    happened to be in the Agnes clip itself, and the chapter music bed.
    Rather than have assemble.py try to extract a search term from freeform
    prose (fragile, would need real NLP), this adds SFX_LINE_RULE: every
    shot must now also end with a short, clean, machine-parseable
    'SFX: <keyword>' line distilling that same sound source into a real
    search term. _retry_missing_sfx() does one bounded corrective pass if
    the model drops the line on any shots (fails open - a plan with a few
    shots missing SFX still ships rather than blocking generation).
    assemble.py's _fetch_shot_sfx() (see that file) is the consuming side -
    it searches the free Freesound.org API with this exact keyword per shot
    and mixes the result in as a new low-volume layer alongside the existing
    native-audio and music layers, degrading silently (no SFX for that shot)
    on any lookup/download failure, matching the fail-open pattern already
    used for music tracks.
    """
    script_uuid = uuid.UUID(str(script_id))
    script = db.query(Script).filter(Script.id == script_uuid).first()
    if not script:
        raise ValueError(f"Script {script_id} not found")

    full_content = script.content
    midpoint = len(full_content) // 2
    split_at = full_content.rfind("\n\n", 0, midpoint + 200)
    if split_at == -1 or split_at < midpoint - 1000:
        split_at = midpoint
    part1_script = full_content[:split_at]
    part2_script = full_content[split_at:]

    part1_target_shots = _estimate_target_shots(part1_script)
    part2_target_shots = _estimate_target_shots(part2_script)

    part1_prompt = (
        f'Create a shot-by-shot video production plan for the FIRST HALF of this '
        f'script:\n\n{part1_script}\n\n'
        f'This first half is approximately {len(part1_script.split())} words of '
        f'narration. Plan for AT MOST {part1_target_shots} shots to give it full '
        f'visual coverage — do not underscope this to a small handful of shots, '
        f'but do not exceed {part1_target_shots} shots either; if there is a lot '
        f'of narration, let individual shots run longer rather than adding more '
        f'of them. List each shot with camera direction, visual style, and '
        f'estimated duration. Vary shot lengths naturally (short punchy cuts vs. '
        f'longer holds) rather than using the same duration for every shot. Keep '
        f'every shot brightly and clearly lit unless the script explicitly calls '
        f'for night or bad weather. Avoid close-ups of readable text or '
        f'documents. Every shot needs both a Duration line and an SFX line. '
        f'Start directly with Shot 1. This is only the first half of '
        f'the script — end at a natural shot boundary, do not add a conclusion '
        f'yet.'
    )
    part1 = _call_gemini(part1_prompt)

    if not part1:
        raise RuntimeError(
            f"Video planning failed on part 1 for script {script_id} "
            f"(Gemini returned nothing usable after {MAX_GENERATION_ATTEMPTS} "
            f"backoff-spaced attempts) - no Video row created, will be retried by "
            f"the supervisor up to MAX_RETRIES."
        )

    part1 = _continue_if_truncated(part1)
    part1 = _retry_missing_sfx(part1, part1_script, part1_target_shots, "Part 1")

    part2_prompt = (
        f'Continue the shot-by-shot production plan directly from where it left '
        f'off, for the SECOND HALF of the same script:\n\n{part2_script}\n\n'
        f'This second half is approximately {len(part2_script.split())} words of '
        f'narration. Plan for AT MOST {part2_target_shots} shots to give it full '
        f'visual coverage — do not underscope this to a small handful of shots, '
        f'but do not exceed {part2_target_shots} shots either; if there is a lot '
        f'of narration, let individual shots run longer rather than adding more '
        f'of them. Here is the shot plan so far for context (do not repeat it, '
        f'only continue numbering from the next shot number):\n\n{part1[-1500:]}\n\n'
        f'Keep the same format: every shot starts with the literal word "Shot" '
        f'followed by a number (never "Scene"), and every shot ends with a '
        f'"Duration: Xs" line followed by an "SFX: <keyword>" line. Vary '
        f'durations naturally. Keep every shot brightly and clearly lit unless '
        f'the script explicitly calls for night or bad weather. Avoid close-ups '
        f'of readable text or documents. Cover this second half through to the '
        f'end of the script.'
    )
    part2 = _call_gemini(part2_prompt)

    if not part2:
        raise RuntimeError(
            f"Video planning failed on part 2 for script {script_id} "
            f"(Gemini returned nothing usable after {MAX_GENERATION_ATTEMPTS} "
            f"backoff-spaced attempts, part 1 succeeded). No Video row created — "
            f"will be retried by the supervisor up to MAX_RETRIES instead of "
            f"shipping a truncated plan."
        )

    part2 = _continue_if_truncated(part2)
    part2 = _retry_missing_sfx(part2, part2_script, part2_target_shots, "Part 2")
    plan = part1 + "\n" + part2

    video = Video(
        title=script.title,
        status="planned",
        views=0,
        topic_id=script.topic_id,
        script_id=script.id,
        production_plan=plan,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return {"video_id": str(video.id), "title": video.title, "status": video.status, "plan_preview": plan[:300]}
