import os
import re
import sys
from datetime import datetime, timezone

import requests

# --- Config from GitHub Actions secrets/env ---
RAILWAY_URL = os.environ["RAILWAY_URL"]
GH_TOKEN = os.environ["GH_TOKEN"]
GH_REPO = os.environ["GH_REPO"]  # "owner/repo"

GH_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
}

# How stuck (hours since last DB update) a video has to be at each stage
# before the supervisor force-triggers that stage directly, instead of
# waiting for the stage's own cron. Set a bit above each workflow's real
# cron interval so this doesn't fire on normal, healthy timing:
#   narrate: hourly-ish       -> 2h grace
#   generate_videos: hourly   -> 3h grace (batches, can take a couple runs)
#   assemble: every 6h        -> 7h grace
#   youtube_upload: every 6h  -> 7h grace
STUCK_HOURS = {
    "narrate": 2,
    "generate_videos": 3,
    "assemble": 7,
    "youtube_upload": 7,
}

WORKFLOW_FILES = {
    "narrate": "narrate.yml",
    "generate_videos": "generate_videos.yml",
    "assemble": "assemble.yml",
    "youtube_upload": "youtube_upload.yml",
}

# If the supervisor has already force-triggered the SAME stage for the SAME
# video this many times with no progress, stop retrying automatically and
# escalate once instead of hammering it forever - at that point it's likely
# a real bug, not a stale cron, and needs a human look.
MAX_AUTO_RETRIES = 3

SHOT_START = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)

# Workflow-failure issues (opened automatically by each workflow's own
# "open issue on failure" step) are matched here by their title keyword, so
# the supervisor can auto-close ones that predate a since-shipped fix.
FAILURE_ISSUE_KEYWORD_TO_SCRIPT = {
    "Narration": ".github/scripts/narrate.py",
    "Assemble": ".github/scripts/assemble.py",
    "Video Generation": ".github/scripts/generate_videos.py",
}


def _parse_shots_count(production_plan):
    count = 0
    for line in (production_plan or "").splitlines():
        line = line.strip()
        if SHOT_START.match(line):
            count += 1
    return count


def _hours_since(iso_ts):
    if not iso_ts:
        return None
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def determine_stage(video):
    """Returns the pipeline stage a video is currently waiting on, or None
    if it's done (uploaded) or not our job yet (no production_plan - still
    at the script-writing stage, outside this pipeline)."""
    status = video.get("status")
    if status == "uploaded":
        return None
    if status == "assembled":
        return "youtube_upload"

    production_plan = video.get("production_plan")
    if not production_plan:
        return None

    if not video.get("audio_path"):
        return "narrate"

    total_shots = _parse_shots_count(production_plan)
    if total_shots == 0:
        return None

    clip_urls = video.get("clip_urls") or []
    if len(clip_urls) < total_shots or not all(clip_urls[:total_shots]):
        return "generate_videos"

    return "assemble"


def trigger_workflow(stage, video_id):
    workflow_file = WORKFLOW_FILES[stage]
    url = f"{GH_API}/repos/{GH_REPO}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": "main", "inputs": {"video_id": video_id}}
    resp = requests.post(url, headers=GH_HEADERS, json=payload, timeout=30)
    if resp.status_code == 204:
        print(f"Triggered {workflow_file} for video {video_id}")
        return True
    print(f"Failed to trigger {workflow_file} for {video_id}: {resp.status_code} {resp.text[:300]}")
    return False


def _search_issues(query):
    resp = requests.get(
        f"{GH_API}/search/issues",
        headers=GH_HEADERS,
        params={"q": query},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def count_prior_retries(stage, video_id):
    result = _search_issues(f'repo:{GH_REPO} is:issue label:supervisor "{video_id}" "{stage}"')
    return result.get("total_count", 0)


def open_issue(title, body, labels):
    resp = requests.post(
        f"{GH_API}/repos/{GH_REPO}/issues",
        headers=GH_HEADERS,
        json={"title": title, "body": body, "labels": labels},
        timeout=30,
    )
    resp.raise_for_status()


def handle_video(video):
    video_id = video["id"]
    title = (video.get("title") or "")[:70]
    stage = determine_stage(video)
    if stage is None:
        return

    hours_stuck = _hours_since(video.get("updated_at"))
    threshold = STUCK_HOURS[stage]
    if hours_stuck is None or hours_stuck < threshold:
        return

    prior_retries = count_prior_retries(stage, video_id)

    if prior_retries >= MAX_AUTO_RETRIES:
        already_escalated = _search_issues(
            f'repo:{GH_REPO} is:issue is:open label:supervisor-escalated "{video_id}"'
        ).get("total_count", 0)
        if already_escalated == 0:
            open_issue(
                title=f"NEEDS HUMAN: video stuck at '{stage}' after {prior_retries} auto-retries - {title}",
                body=(
                    f"Video `{video_id}` ({title}) has been stuck at the **{stage}** stage "
                    f"for {hours_stuck:.1f}h. The supervisor already force-triggered "
                    f"`{WORKFLOW_FILES[stage]}` {prior_retries} times for this exact video "
                    f"with no progress. Not retrying again automatically - this is likely a "
                    f"real bug specific to this video, not a stale cron.\n\n"
                    f"Video status: `{video.get('status')}`\n"
                    f"Last updated: {video.get('updated_at')}\n"
                ),
                labels=["supervisor", "supervisor-escalated"],
            )
            print(f"Escalated {video_id} at stage {stage} after {prior_retries} failed auto-retries.")
        return

    if trigger_workflow(stage, video_id):
        open_issue(
            title=f"Supervisor: force-triggered {stage} for stuck video - {title}",
            body=(
                f"Video `{video_id}` ({title}) was stuck at **{stage}** for {hours_stuck:.1f}h "
                f"(normal threshold: {threshold}h). Supervisor auto-triggered "
                f"`{WORKFLOW_FILES[stage]}` directly for this video_id instead of waiting for "
                f"the normal cron (retry {prior_retries + 1}/{MAX_AUTO_RETRIES}). "
                f"No action needed unless this keeps recurring.\n"
            ),
            labels=["supervisor"],
        )


def auto_close_stale_failure_issues():
    """A workflow-failure issue that predates the most recent commit to
    that workflow's own script was very likely already fixed by that
    commit - close it automatically with a note, instead of leaving Ali to
    manually re-check issues that are already resolved."""
    for keyword, script_path in FAILURE_ISSUE_KEYWORD_TO_SCRIPT.items():
        commits_resp = requests.get(
            f"{GH_API}/repos/{GH_REPO}/commits",
            headers=GH_HEADERS,
            params={"path": script_path, "per_page": 1},
            timeout=30,
        )
        if commits_resp.status_code != 200 or not commits_resp.json():
            continue
        latest_commit_date = commits_resp.json()[0]["commit"]["committer"]["date"]

        issues = _search_issues(
            f'repo:{GH_REPO} is:issue is:open in:title "{keyword} workflow failed"'
        ).get("items", [])

        for issue in issues:
            if issue["created_at"] < latest_commit_date:
                requests.patch(
                    f"{GH_API}/repos/{GH_REPO}/issues/{issue['number']}",
                    headers=GH_HEADERS,
                    json={"state": "closed"},
                    timeout=30,
                )
                requests.post(
                    f"{GH_API}/repos/{GH_REPO}/issues/{issue['number']}/comments",
                    headers=GH_HEADERS,
                    json={
                        "body": (
                            f"Auto-closed by supervisor: this failure was reported before the "
                            f"most recent commit to `{script_path}` ({latest_commit_date}), "
                            f"which likely already fixes it. Reopen if the same failure "
                            f"happens again after this date."
                        )
                    },
                    timeout=30,
                )
                print(f"Auto-closed stale issue #{issue['number']}: {issue['title']}")


def main():
    print("Checking for stale failure issues to auto-close...")
    auto_close_stale_failure_issues()

    print("Fetching all videos from Railway/Render...")
    resp = requests.get(f"{RAILWAY_URL}/api/v1/videos", timeout=90)
    resp.raise_for_status()
    videos = resp.json()
    print(f"Checking {len(videos)} video(s) for stuck stages...")

    for video in videos:
        try:
            handle_video(video)
        except Exception as e:
            print(f"ERROR checking video {video.get('id')}: {type(e).__name__}: {e}", file=sys.stderr)

    print("Supervisor run complete.")


if __name__ == "__main__":
    main()
