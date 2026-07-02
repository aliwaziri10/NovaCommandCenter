import re
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models import Video

SHOT_PATTERN = re.compile(
    r"Shot\s+[\d.]+:\s*(.*?)(?:\s*Camera:|\s*Duration:|$)",
    re.IGNORECASE,
)


def _parse_shots(production_plan: str) -> list[str]:
    """Extract each shot's visual description from the production plan text."""
    shots = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not line.lower().startswith("shot"):
            continue
        match = SHOT_PATTERN.search(line)
        if match:
            desc = match.group(1).strip().rstrip(".")
            if desc:
                shots.append(desc)
    return shots


def run_asset_generation(db: Session, video_id, start_shot: int = 0, count: int = 5):
    """Free version — uses Pollinations.ai image generation, no API key required.
    Processes a small batch of shots at a time (start_shot -> start_shot+count)
    to avoid free-tier timeouts on long videos."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise ValueError(f"Video {video_id} not found")
    if not video.production_plan:
        raise ValueError(f"Video {video_id} has no production_plan to generate assets from")

    all_shots = _parse_shots(video.production_plan)
    batch = all_shots[start_shot:start_shot + count]

    existing_urls = list(video.asset_urls) if video.asset_urls else []
    new_urls = []

    for description in batch:
        prompt = f"{description}, cinematic, hyper-realistic, high detail"
        url = f"https://image.pollinations.ai/prompt/{quote(prompt)}"
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                new_urls.append(url)
            else:
                new_urls.append(None)
        except requests.RequestException:
            new_urls.append(None)

    video.asset_urls = existing_urls + [u for u in new_urls if u]
    db.commit()
    db.refresh(video)

    return {
        "video_id": str(video_id),
        "total_shots": len(all_shots),
        "batch_start": start_shot,
        "batch_count": len(batch),
        "generated": len([u for u in new_urls if u]),
        "failed": len([u for u in new_urls if not u]),
        "asset_urls": video.asset_urls,
    }
