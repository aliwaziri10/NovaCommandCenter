import os
from datetime import datetime, timezone
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
# Optional: Nova's own public channel ID (starts with "UC..."). If unset, the
# self-analytics half of this agent is skipped and it only reports competitors.
NOVA_CHANNEL_ID = os.environ.get("NOVA_YOUTUBE_CHANNEL_ID")

# Default competitor set for the alt-history / "what if" thriller niche.
# Edit this list any time to track different channels — no other code changes needed.
COMPETITOR_HANDLES = [
    "Whatifalthist",
    "AlternateHistoryHub",
    "HistoryMatters",
    "KingsandGenerals",
]


def _resolve_channel_id(handle: str) -> str | None:
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "id", "forHandle": handle, "key": YOUTUBE_API_KEY},
        timeout=20,
    )
    items = resp.json().get("items", [])
    return items[0]["id"] if items else None


def _recent_videos(channel_id: str, max_results: int = 5) -> list[dict]:
    search_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "id",
            "channelId": channel_id,
            "order": "date",
            "maxResults": max_results,
            "type": "video",
            "key": YOUTUBE_API_KEY,
        },
        timeout=20,
    )
    video_ids = [item["id"]["videoId"] for item in search_resp.json().get("items", []) if "videoId" in item.get("id", {})]
    if not video_ids:
        return []

    stats_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet,statistics", "id": ",".join(video_ids), "key": YOUTUBE_API_KEY},
        timeout=20,
    )
    videos = []
    for item in stats_resp.json().get("items", []):
        videos.append({
            "title": item["snippet"]["title"],
            "views": int(item.get("statistics", {}).get("viewCount", 0)),
        })
    return videos


def run_strategy_research(db) -> dict:
    """Pulls recent video titles + public view counts from a fixed set of competitor
    alt-history/thriller channels, plus Nova's own recent public video stats if
    NOVA_YOUTUBE_CHANNEL_ID is set, and distills it into a short text note.

    Meant to run periodically (e.g. weekly), NOT once per video. Returns a plain
    result dict, same as every other agent - tasks_router.py stores it on the task's
    payload. script_writing_agent.py reads the most recent completed task with
    agent_name='strategy_research' to pull the latest note into its prompt, so no
    new database table is needed.

    Uses view counts only (public data via API key). True retention/audience-
    retention data requires the YouTube Analytics API with an OAuth scope this
    project doesn't currently request - a possible future upgrade, not done here.
    """
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY is not set")

    competitor_lines = []
    for handle in COMPETITOR_HANDLES:
        channel_id = _resolve_channel_id(handle)
        if not channel_id:
            continue
        videos = _recent_videos(channel_id)
        if not videos:
            continue
        top = sorted(videos, key=lambda v: v["views"], reverse=True)[0]
        competitor_lines.append(f'- {handle}: "{top["title"]}" ({top["views"]:,} views)')

    self_lines = []
    if NOVA_CHANNEL_ID:
        own_videos = _recent_videos(NOVA_CHANNEL_ID, max_results=5)
        if own_videos:
            own_sorted = sorted(own_videos, key=lambda v: v["views"], reverse=True)
            self_lines = [f'- "{v["title"]}" ({v["views"]:,} views)' for v in own_sorted]

    sections = []
    if competitor_lines:
        sections.append("Recent top-performing titles from tracked competitor channels:\n" + "\n".join(competitor_lines))
    if self_lines:
        sections.append("Nova's own recent videos, best to worst by views:\n" + "\n".join(self_lines))
    if not sections:
        sections.append("No data retrieved this run - check YOUTUBE_API_KEY and channel handles.")

    notes = "\n\n".join(sections)

    return {
        "notes": notes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
