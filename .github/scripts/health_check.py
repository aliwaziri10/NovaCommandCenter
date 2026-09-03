#!/usr/bin/env python3
"""
Nova Command Center - Pipeline Status Report

Runs on the existing Health Check cron (every 6h) and on manual dispatch.
Unlike the old version (which only opened an issue when something failed),
this ALWAYS writes/updates one single pinned issue with a full breakdown of
every video in the pipeline: what's Moving, what's Stuck, and what Needs Fix
(real bugs already flagged by the supervisor). This is the one place Zia (or
Claude, when asked "what's the latest on Nova") can look for an instant,
always-current answer instead of re-deriving pipeline state from scratch
every time.

Design notes:
- Stage detection mirrors supervisor.py's determine_stage() exactly, so this
  report and the supervisor's own actions never disagree about what stage a
  video is waiting on.
- "Needs Fix" pulls real open issues the supervisor already created
  (label: supervisor-escalated) plus any open workflow-failure issues not
  yet auto-closed - it does not re-diagnose bugs, it surfaces the ones
  already confirmed live. Before listing an issue, it re-checks the video's
  current status/youtube_video_id and auto-closes the issue if the video has
  since completed - the supervisor and workflows don't reliably close these
  themselves once a stuck video later recovers.
- This script never triggers workflows or force-fixes anything itself -
  that job belongs to supervisor.py. This is read-only reporting (aside from
  closing confirmed-stale issues, which is a report-integrity action, not a
  pipeline action).
"""

import os
import re
import json
import subprocess
from datetime import datetime, timezone

import requests

RAILWAY_URL = os.environ["RAILWAY_URL"].rstrip("/")
VIDEOS_ENDPOINT = f"{RAILWAY_URL}/api/v1/videos"
GH_REPO = os.environ.get("GH_REPO", "")

STATUS_ISSUE_TITLE = "[Nova Pipeline Status] Latest report"

# Same per-stage grace periods as supervisor.py, used here only to decide
# Moving vs Stuck for the report (never to trigger anything).
STUCK_HOURS = {
    "narrate": 2,
    "generate_videos": 3,
    "assemble": 7,
    "youtube_upload": 7,
}

SHOT_START = re.compile(r"^[\-\*\s]*\**(?:shot\s*[\d.]+|\d+[\.\)])\**", re.IGNORECASE)

# Matches a video's id (uuid) anywhere in an issue's title or body, so we can
# tell which video a given "stuck"/"workflow failed" issue was about.
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def parse_dt(value):
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hours_since(iso_ts, now):
    dt = parse_dt(iso_ts)
    if not dt:
        return None
    return (now - dt).total_seconds() / 3600.0


def parse_shots_count(production_plan):
    count = 0
    for line in (production_plan or "").splitlines():
        line = line.strip()
        if SHOT_START.match(line):
            count += 1
    return count


def determine_stage(video):
    """Mirrors supervisor.py's determine_stage(). Returns the stage a video
    is currently waiting on, or None if it's done (uploaded) or not yet in
    this pipeline (no production_plan - still at script-writing)."""
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

    total_shots = parse_shots_count(production_plan)
    if total_shots == 0:
        return None

    clip_urls = video.get("clip_urls") or []
    if len(clip_urls) < total_shots or not all(clip_urls[:total_shots]):
        return "generate_videos"

    return "assemble"


def fetch_videos():
    resp = requests.get(VIDEOS_ENDPOINT, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data.get("videos", data.get("data", []))
    return data


def fetch_open_issues(label_or_query):
    """Uses gh CLI (already authenticated in the workflow) to search issues."""
    result = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--search", label_or_query,
         "--json", "number,title,url,createdAt,body", "--limit", "30"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Warning: gh issue list failed for query {label_or_query!r}: {result.stderr}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def close_stale_issue(issue, video):
    yt_id = video.get("youtube_video_id", "")
    reason = (
        f"Video is confirmed `status=uploaded`"
        + (f" (youtube_video_id {yt_id})" if yt_id else "")
        + " in live DB. Auto-closing as stale - this issue was opened while the "
        "video was stuck, but the video has since completed."
    )
    subprocess.run(
        ["gh", "issue", "comment", str(issue["number"]), "--body", reason],
        capture_output=True, text=True,
    )
    result = subprocess.run(
        ["gh", "issue", "close", str(issue["number"]), "--reason", "completed"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Warning: could not auto-close issue #{issue['number']}: {result.stderr}")
        return False
    print(f"Auto-closed stale issue #{issue['number']} (video now uploaded).")
    return True


def reconcile_needs_fix_issues(issues, videos_by_id):
    """Drops any issue from the Needs Fix list whose referenced video has
    since reached status=uploaded, closing that issue on GitHub too so it
    doesn't keep coming back as a false bug report."""
    still_open = []
    for issue in issues:
        haystack = f"{issue.get('title', '')}\n{issue.get('body', '')}"
        match = UUID_RE.search(haystack)
        video = videos_by_id.get(match.group(0)) if match else None
        if video and video.get("status") == "uploaded":
            close_stale_issue(issue, video)
            continue
        still_open.append(issue)
    return still_open


def classify_videos(videos, now):
    moving, stuck, done = [], [], []
    for v in videos:
        stage = determine_stage(v)
        if stage is None:
            if v.get("status") == "uploaded":
                done.append(v)
            continue

        age = hours_since(v.get("updated_at"), now)
        threshold = STUCK_HOURS.get(stage, 6)
        entry = {
            "id": v.get("id", "unknown"),
            "title": (v.get("title") or "Untitled")[:70],
            "stage": stage,
            "age_hours": age,
        }
        if age is not None and age > threshold:
            stuck.append(entry)
        else:
            moving.append(entry)
    return moving, stuck, done


def build_report_body(videos, moving, stuck, needs_fix_issues, now):
    lines = [
        f"_Last generated: {now.strftime('%Y-%m-%d %H:%M UTC')} - this issue is updated in place every run, not reposted._",
        "",
        f"**Totals:** {len(videos)} videos tracked | {len(moving)} moving | {len(stuck)} stuck | {len(needs_fix_issues)} open bugs flagged",
        "",
        "## Moving forward",
    ]
    if moving:
        for e in sorted(moving, key=lambda x: x["age_hours"] or 0, reverse=True):
            age_str = f"{e['age_hours']:.1f}h ago" if e["age_hours"] is not None else "unknown age"
            lines.append(f"- `{e['id']}` \u2014 *{e['title']}* \u2014 at **{e['stage']}**, last moved {age_str}")
    else:
        lines.append("- Nothing currently in active progress.")

    lines += ["", "## Stuck (past normal threshold for its stage)"]
    if stuck:
        for e in sorted(stuck, key=lambda x: x["age_hours"] or 0, reverse=True):
            lines.append(
                f"- `{e['id']}` \u2014 *{e['title']}* \u2014 stuck at **{e['stage']}** for {e['age_hours']:.1f}h "
                f"(supervisor will force-retry or has already escalated this)"
            )
    else:
        lines.append("- Nothing stuck right now.")

    lines += ["", "## Needs fix (confirmed bugs, not just staleness)"]
    if needs_fix_issues:
        for issue in needs_fix_issues:
            lines.append(f"- [#{issue['number']}]({issue['url']}) {issue['title']}")
    else:
        lines.append("- No open supervisor-escalated or unresolved workflow-failure issues.")

    lines += ["", "## Recently uploaded (done, awaiting/after manual review+publish)"]
    recent_done = sorted(videos, key=lambda v: v.get("updated_at") or "", reverse=True)
    recent_done = [v for v in recent_done if v.get("status") == "uploaded"][:5]
    if recent_done:
        for v in recent_done:
            yt_id = v.get("youtube_video_id", "")
            link = f"https://youtube.com/watch?v={yt_id}" if yt_id else "(no youtube id on record)"
            lines.append(f"- *{(v.get('title') or 'Untitled')[:70]}* \u2014 {link}")
    else:
        lines.append("- None yet.")

    return "\n".join(lines)


def get_status_issue_number():
    result = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--search", STATUS_ISSUE_TITLE,
         "--json", "number,title"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        issues = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for issue in issues:
        if issue["title"] == STATUS_ISSUE_TITLE:
            return issue["number"]
    return None


def ensure_label_exists():
    """Creates the 'pipeline-status' label if it doesn't exist yet. gh issue
    create fails hard on an unknown label, so this is checked once up front
    instead of assuming the label was ever manually created in the repo."""
    result = subprocess.run(
        ["gh", "label", "list", "--search", "pipeline-status", "--json", "name"],
        capture_output=True, text=True,
    )
    existing_names = []
    if result.returncode == 0:
        try:
            existing_names = [l["name"] for l in json.loads(result.stdout)]
        except json.JSONDecodeError:
            pass
    if "pipeline-status" in existing_names:
        return True
    create_result = subprocess.run(
        ["gh", "label", "create", "pipeline-status",
         "--description", "Auto-generated Nova pipeline status report",
         "--color", "0E8A16"],
        capture_output=True, text=True,
    )
    if create_result.returncode != 0:
        print(f"Warning: could not create 'pipeline-status' label: {create_result.stderr}")
        return False
    return True


def write_status_issue(body):
    existing = get_status_issue_number()
    if existing:
        subprocess.run(
            ["gh", "issue", "edit", str(existing), "--body", body],
            check=True,
        )
        print(f"Updated pipeline status issue #{existing}.")
        return

    label_args = []
    if ensure_label_exists():
        label_args = ["--label", "pipeline-status"]
    subprocess.run(
        ["gh", "issue", "create", "--title", STATUS_ISSUE_TITLE, "--body", body] + label_args,
        check=True,
    )
    print("Created pipeline status issue.")


def main():
    now = datetime.now(timezone.utc)

    try:
        videos = fetch_videos()
    except Exception as e:
        print(f"Failed to fetch videos from {VIDEOS_ENDPOINT}: {e}")
        # Still try to write a report noting the backend itself is unreachable -
        # that IS the status, not a reason to stay silent.
        body = (
            f"_Last generated: {now.strftime('%Y-%m-%d %H:%M UTC')}_\n\n"
            f"**Backend unreachable.** Could not fetch videos from `{VIDEOS_ENDPOINT}`: `{e}`. "
            f"This is itself the top-priority issue right now - the Render backend may be down "
            f"or crashed.\n"
        )
        write_status_issue(body)
        raise

    videos_by_id = {v.get("id"): v for v in videos if v.get("id")}

    moving, stuck, _ = classify_videos(videos, now)

    needs_fix_issues = fetch_open_issues("label:supervisor-escalated")
    needs_fix_issues += fetch_open_issues('in:title "workflow failed"')
    # De-dupe by issue number in case a query matched twice
    seen = set()
    deduped = []
    for issue in needs_fix_issues:
        if issue["number"] not in seen:
            seen.add(issue["number"])
            deduped.append(issue)
    needs_fix_issues = reconcile_needs_fix_issues(deduped, videos_by_id)

    body = build_report_body(videos, moving, stuck, needs_fix_issues, now)
    write_status_issue(body)

    print(f"Report written: {len(moving)} moving, {len(stuck)} stuck, {len(needs_fix_issues)} bugs flagged.")


if __name__ == "__main__":
    main()
