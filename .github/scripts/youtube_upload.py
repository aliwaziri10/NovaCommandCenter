import time
import requests

# Replace the existing BACKEND_TIMEOUT constant near the top of the file with this:
BACKEND_TIMEOUT = 120  # was 90 — Render cold starts can run past 90s

# Replace the existing wake_up_backend() function (around line 39) with this:
def wake_up_backend(max_attempts=4):
    """
    Wakes a sleeping Render free-tier instance before hitting the real endpoint.
    Uses growing backoff between attempts instead of firing back-to-back,
    since a cold instance needs time to boot before it can even accept
    a new connection.
    """
    backoff_seconds = [10, 20, 40, 60]

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(
                f"{RAILWAY_URL}/api/v1/videos",
                timeout=BACKEND_TIMEOUT,
            )
            return resp
        except requests.exceptions.ReadTimeout:
            print(f"Backend not awake yet (attempt {attempt}/{max_attempts}): read timeout after {BACKEND_TIMEOUT}s")
        except requests.exceptions.ConnectionError as e:
            print(f"Backend not reachable yet (attempt {attempt}/{max_attempts}): {e}")

        if attempt < max_attempts:
            wait = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
            print(f"Waiting {wait}s before retry...")
            time.sleep(wait)

    raise RuntimeError(
        f"Backend at {RAILWAY_URL} did not respond after {max_attempts} attempts. "
        "Check Render dashboard for deploy/crash status."
    )
