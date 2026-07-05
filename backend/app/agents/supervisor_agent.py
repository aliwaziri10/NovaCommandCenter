import json
import os
from datetime import datetime
from sqlalchemy.orm import Session

from app.models import Topic, Script, Video, Task
from app.agents.topic_research_agent import run_topic_research
from app.agents.script_writing_agent import run_script_writing
from app.agents.video_planning_agent import run_video_planning
from app.agents.asset_generation_agent import run_asset_generation, _parse_shots
from app.agents.narration_agent import run_narration
from app.agents.assembly_agent import run_assembly

MAX_RETRIES = 2
MIN_TOPICS_IN_PIPELINE = 3
ASSET_BATCH_SIZE = 5
LOG_PATH = "/app/data/supervisor_log.json"


def _failed_attempts(db: Session, agent_name: str, id_key: str, id_value: str) -> int:
    tasks = db.query(Task).filter(Task.agent_name == agent_name, Task.status == "failed").all()
    count = 0
    for t in tasks:
        payload = t.payload or {}
        if str(payload.get(id_key)) == str(id_value):
            count += 1
    return count


def _has_active_task(db: Session, agent_name: str, id_key: str, id_value: str) -> bool:
    tasks = db.query(Task).filter(
        Task.agent_name == agent_name,
        Task.status.in_(["pending", "running"]),
    ).all()
    for t in tasks:
        payload = t.payload or {}
        if str(payload.get(id_key)) ==
