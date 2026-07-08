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
