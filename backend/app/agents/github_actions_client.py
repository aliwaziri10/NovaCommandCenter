import os
import requests

GITHUB_PAT = os.environ.get("GITHUB_PAT")
GITHUB_REPO = "aliwaziri10/NovaCommandCenter"
GITHUB_API_BASE = "https://api.github.com"


def trigger_workflow(workflow_filename, inputs):
    """Triggers a GitHub Actions workflow_dispatch run.
    workflow_filename: e.g. "generate_videos.yml"
    inputs: dict matching the workflow's declared inputs (all values must be strings)
    Returns True if GitHub accepted the trigger request, False otherwise.
    """
    if not GITHUB_PAT:
        print("WARNING: GITHUB_PAT not set, cannot trigger workflow.")
        return False

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/actions/workflows/{workflow_filename}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
    }
    body = {
        "ref": "main",
        "inputs": {k: str(v) for k, v in inputs.items()},
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        if resp.status_code == 204:
            print(f"Triggered workflow {workflow_filename} with inputs {inputs}")
            return True
        print(f"WARNING: failed to trigger {workflow_filename}: HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        print(f"WARNING: error triggering {workflow_filename}: {type(e).__name__}: {str(e)[:150]}")
        return False


def open_issue(title, body, labels=None):
    """Opens a GitHub Issue on this repo via the REST API (not a workflow
    step, so this works from any backend context, not just inside a
    GitHub Actions run).

    ADDED (2026-08-28): used by supervisor_agent.py to surface permanently
    abandoned tasks (those that hit MAX_RETRIES) - previously these were
    dropped from the supervisor's rotation silently, with no alert of any
    kind, so a topic/script/video could sit stuck forever with nothing
    telling Ali it needed a look. Reuses the same GITHUB_PAT already used
    for trigger_workflow - no new secret needed, but that PAT must have
    the "Issues: write" repository permission or this will fail (silently,
    by design - see caller, this must never raise and break the
    supervisor cycle over a notification failure).

    Returns True if GitHub accepted the issue creation, False otherwise
    (never raises).
    """
    if not GITHUB_PAT:
        print("WARNING: GITHUB_PAT not set, cannot open issue.")
        return False

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
    }
    body = {"title": title, "body": body}
    if labels:
        body["labels"] = labels
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        if resp.status_code == 201:
            print(f"Opened issue: {title}")
            return True
        print(f"WARNING: failed to open issue '{title}': HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        print(f"WARNING: error opening issue '{title}': {type(e).__name__}: {str(e)[:150]}")
        return False
