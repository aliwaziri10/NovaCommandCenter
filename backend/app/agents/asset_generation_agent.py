import re
import time
import uuid
import requests
from urllib.parse import quote
from sqlalchemy.orm import Session
from app.models import Video

SHOT_START = re.compile(r"^[\-\*\s]*\**shot\s*[\d.]+\**", re.IGNORECASE)

IMAGE_MODEL = "flux"
IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080


def _parse_shots(production_plan: str) -> list[str]:
    """Extract each shot's visual description from the production plan text.
    Handles both 'Shot 1.1: desc Camera: ... Duration: 4s' style and
    '**Shot 1** – desc ... **Duration:** 4 s' markdown style."""
    shots = []
    for line in production_plan.splitlines():
        line = line.strip()
        if not SHOT_START.match(line):
            continue
        remainder = SHOT_START.sub("", line).strip()
        remainder = re.sub(r"^[\s:\-–\*]+", "", remainder)
        remainder = re.split(r"\*{0,2}Duration\*{0,2}\s*:", remainder, maxsplit=1, flags=re.IGNORECASE)[0]
        remainder = re.split(r"\bCamera\s*:", remainder, maxsplit=1, flags=re.IGNORECASE)[0]
        remainder = remainder.replace("**", "").replace("*", "").strip().rstrip(".").strip()
        if remainder:
            shots.append(remainder)
    return shots


def run_asset_generation(db: Session, video_id, start_shot: int = 0, count: int = 5):
    """Free version — uses Pollinations.ai image generation, no API key required.
    Processes a small batch of shots at a time (start_shot -> start_shot+count)
    to avoid free-tier timeouts on long videos."""
    if isinstance(video_id, str):
        video_id = uuid.UUID(video_id)
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise ValueError(f"Video {video_id} not found")
    if not video.production_plan:
        raise ValueError(f"Video {video_id} has no production_plan to generate assets from")

    all_shots = _parse_shots(video.production_plan)
    batch = all_shots[start_shot:start_shot + count]
    existing_urls = list(video.asset_urls) if video.asset_urls else []
    new_urls = []
    failure_reasons = []

    for description in batch:
        prompt = (
            f"{description}, cinematic documentary photography, "
            f"hyper-realistic, ultra detailed, dramatic lighting, 8k, film grain, "
            f"professional color grading, widescreen composition"
        )
        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            f"?model={IMAGE_MODEL}&width={IMAGE_WIDTH}&height={IMAGE_HEIGHT}"
        )
        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                new_urls.append(url)
            else:
                new_urls.append(None)
                failure_reasons.append(f"{description[:40]}... -> HTTP {response.status_code}")
        except requests.RequestException as e:
            new_urls.append(None)
            failure_reasons.append(f"{description[:40]}... -> {type(e).__name__}: {str(e)[:100]}")
        time.sleep(3)

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
        "failure_reasons": failure_reasons,
        "asset_urls": video.asset_urls,
    }
