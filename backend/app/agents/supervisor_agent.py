import json
import os
from datetime import datetime, timedelta
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
STALE_TASK_MINUTES = 30
LOG_PATH = "/app/data/supervisor_log.json"


def _clear_stale_tasks(db):
    """Any task stuck in pending/running past the timeout is marked failed
    so it stops permanently blocking the Supervisor's active-task check."""
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_TASK_MINUTES)
    stuck = db.query(Task).filter(
        Task.status.in_(["pending", "running"]),
        Task.created_at < cutoff,
    ).all()
    for t in stuck:
        t.status = "failed"
        merged = dict(t.payload or {})
        merged["error"] = "Marked failed by supervisor: exceeded " + str(STALE_TASK_MINUTES) + " minute stale timeout."
        t.payload = merged
    if stuck:
        db.commit()
    return len(stuck)


def _failed_attempts(db, agent_name, id_key, id_value):
    tasks = db.query(Task).filter(Task.agent_name == agent_name, Task.status == "failed").all()
    count = 0
    for t in tasks:
        payload = t.payload or {}
        if str(payload.get(id_key)) == str(id_value):
            count = count + 1
    return count


def _has_active_task(db, agent_name, id_key, id_value):
    tasks = db.query(Task).filter(
        Task.agent_name == agent_name,
        Task.status.in_(["pending", "running"]),
    ).all()
    for t in tasks:
        payload = t.payload or {}
        if str(payload.get(id_key)) == str(id_value):
            return True
    return False


def _find_next_task(db):
    videos = db.query(Video).filter(Video.status != "assembled").all()

    for video in videos:
        if not video.asset_urls or not video.production_plan or not video.audio_path:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if total_shots and len(video.asset_urls) >= total_shots:
            vid = str(video.id)
            if _has_active_task(db, "assembly", "video_id", vid):
                continue
            if _failed_attempts(db, "assembly", "video_id", vid) >= MAX_RETRIES:
                continue
            return {"agent_name": "assembly", "payload": {"video_id": vid}, "title": "Assemble video " + vid[:8]}

    for video in videos:
        if not video.asset_urls or not video.production_plan or video.audio_path:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if total_shots and len(video.asset_urls) >= total_shots:
            vid = str(video.id)
            if _has_active_task(db, "narration", "video_id", vid):
                continue
            if _failed_attempts(db, "narration", "video_id", vid) >= MAX_RETRIES:
                continue
            return {"agent_name": "narration", "payload": {"video_id": vid}, "title": "Narrate video " + vid[:8]}

    for video in videos:
        if not video.production_plan:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if not total_shots:
            continue
        have = len(video.asset_urls) if video.asset_urls else 0
        if have < total_shots:
            vid = str(video.id)
            if _has_active_task(db, "asset_generation", "video_id", vid):
                continue
            if _failed_attempts(db, "asset_generation", "video_id", vid) >= MAX_RETRIES:
                continue
            return {
                "agent_name": "asset_generation",
                "payload": {"video_id": vid, "start_shot": have, "count": ASSET_BATCH_SIZE},
                "title": "Generate shots for video " + vid[:8],
            }

    scripts = db.query(Script).all()
    for script in scripts:
        has_video = db.query(Video).filter(Video.script_id == script.id).first()
        if has_video:
            continue
        sid = str(script.id)
        if _has_active_task(db, "video_planning", "script_id", sid):
            continue
        if _failed_attempts(db, "video_planning", "script_id", sid) >= MAX_RETRIES:
            continue
        return {"agent_name": "video_planning", "payload": {"script_id": sid}, "title": "Plan video for script " + sid[:8]}

    topics = db.query(Topic).all()
    for topic in topics:
        has_script = db.query(Script).filter(Script.topic_id == topic.id).first()
        if has_script:
            continue
        tid = str(topic.id)
        if _has_active_task(db, "script_writing", "topic_id", tid):
            continue
        if _failed_attempts(db, "script_writing", "topic_id", tid) >= MAX_RETRIES:
            continue
        return {"agent_name": "script_writing", "payload": {"topic_id": tid}, "title": "Write script for topic " + tid[:8]}

    topics_without_scripts = []
    for t in topics:
        has_script = db.query(Script).filter(Script.topic_id == t.id).first()
        if not has_script:
            topics_without_scripts.append(t)

    if len(topics_without_scripts) < MIN_TOPICS_IN_PIPELINE:
        if _has_active_task(db, "topic_research", "category", "History"):
            return None
        return {"agent_name": "topic_research", "payload": {"category": "History"}, "title": "Research new topics"}

    return None


def _execute(db, agent_name, payload):
    if agent_name == "topic_research":
        return run_topic_research(db, category=payload.get("category", "History"))
    if agent_name == "script_writing":
        return run_script_writing(db, topic_id=payload["topic_id"])
    if agent_name == "video_planning":
        return run_video_planning(db, script_id=payload["script_id"])
    if agent_name == "asset_generation":
        return run_asset_generation(
            db,
            video_id=payload["video_id"],
            start_shot=payload.get("start_shot", 0),
            count=payload.get("count", 5),
        )
    if agent_name == "narration":
        return run_narration(db, video_id=payload["video_id"])
    if agent_name == "assembly":
        return run_assembly(db, video_id=payload["video_id"])
    raise ValueError("Unknown agent_name: " + str(agent_name))


def _write_log(entry):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w") as f:
            json.dump(entry, f, default=str)
    except Exception:
        pass


def run_supervisor_cycle(db):
    started_at = datetime.utcnow()

    cleared = _clear_stale_tasks(db)

    next_action = _find_next_task(db)

    if not next_action:
        result = {
            "timestamp": str(started_at),
            "action": "idle",
            "message": "Nothing to do this cycle.",
            "stale_tasks_cleared": cleared,
        }
        _write_log(result)
        return result

    task = Task(
        title=next_action["title"],
        agent_name=next_action["agent_name"],
        status="running",
        priority=1,
        payload=next_action["payload"],
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        output = _execute(db, next_action["agent_name"], next_action["payload"])
        task.status = "completed"
        merged = dict(task.payload or {})
        merged["result"] = output
        task.payload = merged
        db.commit()
        result = {
            "timestamp": str(started_at),
            "action": "completed",
            "agent_name": next_action["agent_name"],
            "task_id": str(task.id),
            "title": next_action["title"],
            "stale_tasks_cleared": cleared,
        }
    except Exception as e:
        task.status = "failed"
        merged = dict(task.payload or {})
        merged["error"] = str(e)
        task.payload = merged
        db.commit()
        result = {
            "timestamp": str(started_at),
            "action": "failed",
            "agent_name": next_action["agent_name"],
            "task_id": str(task.id),
            "title": next_action["title"],
            "error": str(e),
            "stale_tasks_cleared": cleared,
        }

    _write_log(result)
    return result
