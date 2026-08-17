#!/usr/bin/env python3
"""
Nova Command Center - Health Check

Checks live video pipeline state via the Render backend API and opens/updates/closes
a GitHub issue reflecting current health. Mirrors Marius's health_check.py pattern,
adapted to Nova's actual API (Render backend /api/v1/videos, no direct Supabase access
from GitHub Actions — only RAILWAY_URL secret is available, value is the Render URL).
"""

import os
import re
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta

import requests

RAILWAY_URL = os.environ["RAILWAY_URL"].rstrip("/")
VIDEOS_ENDPOINT = f"{RAILWAY_URL}/api/v1/videos"

STALENESS_THRESHOLD_HOURS = 30
STUCK_PLANNED_THRESHOLD_HOURS = 48

ISSUE_TITLE_PREFIX = "[Nova Health Check] Active alert"


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


def count_shots_in_plan(production_plan):
    """Count shots via regex on lines starting with 'Shot N:' (case-insensitive)."""
    if not production_plan:
        return 0
    text = production_plan if isinstance(production_plan, str) else json.dumps(production_plan)
    matches = re.findall(r"shot\s+\d+\s*:", text, re.IGNORECASE)
    return len(matches)


def count_filled_clip_urls(clip_urls):
    if not clip_urls:
        return 0
    if isinstance(clip_urls, list):
        return sum(1 for u in clip_urls if u)
    return 0


def fetch_videos():
    resp = requests.get(VIDEOS_ENDPOINT, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data.get("videos", data.get("data", []))
    return data


def check_staleness(videos, now):
    if not videos:
        return None
    newest = max(
        (v for v in videos if parse_dt(v.get("created_at"))),
        key=lambda v: parse_dt(v.get("created_at")),
        default=None,
    )
    if not newest:
        return "No videos with a valid created_at found — cannot verify pipeline is producing output."
    newest_dt = parse_dt(newest.get("created_at"))
    age_hours = (now - newest_dt).total_seconds() / 3600
    if age_hours > STALENESS_THRESHOLD_HOURS:
        return (
            f"Newest video ({newest.get('id', 'unknown')}) was created "
            f"{age_hours:.1f}h ago, exceeding the {STALENESS_THRESHOLD_HOURS}h staleness threshold."
        )
    return None


def check_stuck_planned(videos, now):
    problems = []
    for v in videos:
        if v.get("status") != "planned":
            continue
        updated_dt = parse_dt(v.get("updated_at"))
        if not updated_dt:
            continue
        age_hours = (now - updated_dt).total_seconds() / 3600
        if age_hours <= STUCK_PLANNED_THRESHOLD_HOURS:
            continue
        shot_count = count_shots_in_plan(v.get("production_plan"))
        filled = count_filled_clip_urls(v.get("clip_urls"))
        if shot_count and filled < shot_count:
            problems.append(
                f"Video {v.get('id', 'unknown')} stuck in 'planned' for {age_hours:.1f}h "
                f"with {filled}/{shot_count} shot clips filled."
            )
    return problems


def get_open_health_issue():
    result = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--search", ISSUE_TITLE_PREFIX, "--json", "number,title"],
        capture_output=True, text=True, check=True,
    )
    issues = json.loads(result.stdout)
    for issue in issues:
        if issue["title"].startswith(ISSUE_TITLE_PREFIX):
            return issue["number"]
    return None


def open_or_update_issue(problems, now):
    date_str = now.strftime("%Y-%m-%d")
    title = f"{ISSUE_TITLE_PREFIX} - {date_str}"
    body_lines = [
        f"Health check run at {now.isoformat()}",
        "",
        "Detected issues:",
        "",
    ] + [f"- {p}" for p in problems]
    body = "\n".join(body_lines)

    existing = get_open_health_issue()
    if existing:
        subprocess.run(
            ["gh", "issue", "comment", str(existing), "--body", body],
            check=True,
        )
        subprocess.run(
            ["gh", "issue", "edit", str(existing), "--title", title],
            check=True,
        )
    else:
        subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body", body],
            check=True,
        )


def close_issue_if_open():
    existing = get_open_health_issue()
    if existing:
        subprocess.run(
            ["gh", "issue", "comment", str(existing), "--body", "Health check passed — closing."],
            check=True,
        )
        subprocess.run(
            ["gh", "issue", "close", str(existing)],
            check=True,
        )


def main():
    now = datetime.now(timezone.utc)

    try:
        videos = fetch_videos()
    except Exception as e:
        print(f"Failed to fetch videos from {VIDEOS_ENDPOINT}: {e}")
        sys.exit(1)

    problems = []

    staleness_problem = check_staleness(videos, now)
    if staleness_problem:
        problems.append(staleness_problem)

    problems.extend(check_stuck_planned(videos, now))

    if problems:
        print("Health check FAILED:")
        for p in problems:
            print(f"  - {p}")
        open_or_update_issue(problems, now)
        sys.exit(1)
    else:
        print("Health check PASSED.")
        close_issue_if_open()
        sys.exit(0)


if __name__ == "__main__":
    main()
