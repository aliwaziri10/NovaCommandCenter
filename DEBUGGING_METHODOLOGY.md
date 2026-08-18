# Debugging Methodology — Mandatory for Every AI Agent Working on Atlas Frame Pipelines

This file exists because of a real incident (2026-08-18, Nova Command Center).
An earlier diagnosis chain guessed at three different root causes in a row
(a guard-logic revert, a Groq daily-quota theory, an OpenRouter-model theory)
before actually reading and running the real code against real data. Each
guess was plausible-sounding and each was wrong or unconfirmed. The person
overseeing these pipelines (Zia) is not a coder and cannot verify these
guesses himself — every wrong diagnosis costs him trust and wastes real
engineering time. This standard is designed to make that failure mode
structurally difficult to repeat, for any agent (Claude or otherwise)
working on any of the three pipelines (Marius, Nova, TechPulse).

## The rule, stated plainly

**Never state a root cause with confidence until it has been PROVEN by
execution, not just inferred by reading.** Reading code and reasoning about
what it "should" do is a hypothesis. Running that exact code against real
data pulled from the live system, and observing the actual output, is
evidence. Only evidence earns a confident claim.

## The process, in order, every time

1. **Gather the real symptom first.** Pull the actual failed run's log
   output (FAILURE SUMMARY block, full traceback, or equivalent). Do not
   diagnose from an issue title or a one-line summary — those describe the
   symptom, not the cause. If log access isn't available via any loaded
   tool, say so explicitly and ask for it to be pasted in — don't guess
   around the gap.

2. **Read the actual live code, not a memory of it, not a docstring's
   description of what it does, not a CODEMAP summary.** Fetch the file
   fresh every time. A docstring can claim a bug was fixed on a specific
   date and still be wrong — the only ground truth is the code itself.

3. **Pull the actual live data the failing code was operating on** (the
   real Supabase row, the real API response, the real file content) —
   not a synthetic or imagined example of what that data "probably"
   looks like.

4. **Trace the code against that real data by hand, line by line**, if a
   full local repro isn't yet built. Write down the trace, don't just
   assert the conclusion.

5. **Then actually run it.** Use the bash/code-execution tool to copy the
   real function and the real data into a script and execute it. Compare
   the printed output to the real observed symptom. If they match, the
   hypothesis is confirmed by evidence, not argument. If they don't
   match, the hypothesis is wrong — go back to step 1, don't rationalize
   the mismatch away.

6. **Before proposing a fix, test the fix the same way** — run the
   proposed corrected code against the same real failing data AND against
   at least one real *working* case, to confirm the fix resolves the
   failure without breaking what already works. A fix that isn't verified
   against a known-good case can silently introduce a regression.

7. **Report findings with precision about what's proven vs. still
   uncertain.** If something is confirmed by execution, say so plainly.
   If something is still a theory, say "unconfirmed" or "hypothesis" —
   never phrase a guess as a finding.

8. **Rule out alternative explanations explicitly**, especially the
   boring ones: transient infra (502s, rate limits, queue-full errors)
   that self-heal on retry are NOT bugs and should not trigger a code
   change — confirm via live data (e.g., did the affected row's status
   change to success on a later timestamp?) before treating a single
   failed run as a systemic problem.

9. **Do not rush.** A wrong fix shipped fast is worse than a right fix
   shipped slow — it can actively make things worse (see: reverting a
   guard that wasn't the cause, or resetting a topic whose real failure
   reason was never checked). Multiple angles of attack on the same
   symptom, actively trying to falsify your own leading theory, is the
   correct pace — not the exception.

10. **Only after all the above, take action** (write a fix, reset a
    status, revert a commit) — and note in the commit message / status
    update exactly what evidence supports it, so the next agent (or
    Zia) can see the reasoning, not just the result.

## What this looked like in practice (2026-08-18 Nova case study)

- Symptom: two videos stuck at `generate_videos`, 0 shots parsed.
- Wrong early guesses (not verified, correctly abandoned): a guard-logic
  regression from a recent refactor; a Groq daily quota bug (this was
  actually a *different* pipeline, Marius — a reminder to not cross-wire
  findings between pipelines either).
- Real process: pulled the actual `generate_videos.py` `_parse_shots()`
  function fresh from GitHub. Pulled the actual `production_plan` text for
  both stuck videos directly from Supabase. Hand-traced the parser against
  that real text and found a suspected state-tracking bug (`current_parts`
  truthiness used as a proxy for "inside a shot block," which fails when a
  shot's header line has zero inline text). Did NOT stop at the hand
  trace — used the bash tool to literally paste the real function and the
  real data into a script and ran it. Output: 0 shots parsed, exactly
  matching the live symptom. Then wrote the proposed fix, ran it against
  the same two failing cases (fixed: 3 and 2 shots respectively) AND
  against a known-working normal-format case (still 2 shots, unchanged) —
  confirming the fix resolves the bug without regressing the working path.
- Only at that point was the root cause stated as confirmed, not guessed.

## Standing priority

This methodology takes priority over speed. Every agent working on Marius,
Nova, or TechPulse must follow this before stating any diagnosis as fact,
and must use the code-execution tool to verify a hypothesis whenever the
tooling allows it — hand-tracing alone is not sufficient when execution
is available.
