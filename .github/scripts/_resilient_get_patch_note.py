def _resilient_get(url, max_attempts=8, **kwargs):
    """COLD-START FIX (2026-08-21): Render's free-tier backend spins down
    after ~15 min idle and cold-starts on the next request. This script
    runs on a GitHub Actions cron, so its very first request to the
    backend can land during that cold-start window and get a connection
    error or a 502/503 from Render's edge before the app is ready. With
    no retry, that killed the ENTIRE run before any real work started -
    confirmed live: assemble workflow run #301 failed within seconds of
    the backend container even finishing its boot
    (2026-08-21T02:54:41Z fail vs 02:54:49-02:55:07Z container startup
    in Render's own logs). Retrying with backoff means a cold start no
    longer aborts the whole job.

    WIDENED (2026-08-31): max_attempts was 5 (10/20/30/40s backoff, ~100s
    total). Confirmed live on run #366: the very first call of the whole
    script (this one, fetching /api/v1/videos) failed all 5 attempts with
    503 within 100s of a run that also landed shortly after several other
    commits had just been pushed to this repo's backend/ - i.e. Render
    was plausibly still mid-redeploy or freshly restarting when this run
    fired, which can extend a cold start well past a typical ~30-60s
    window. Raised to 8 attempts / longer backoff cap for headroom on
    exactly this kind of stacked-redeploy timing, without changing
    behavior at all for the common case (a healthy backend still answers
    on attempt 1).
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, **kwargs)
            if resp.status_code in (502, 503, 504):
                raise requests.RequestException(
                    f"backend not ready yet (HTTP {resp.status_code})"
                )
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt == max_attempts:
                break
            wait = min(10 * attempt, 60)
            print(f"Backend not ready (attempt {attempt}/{max_attempts}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise last_exc
