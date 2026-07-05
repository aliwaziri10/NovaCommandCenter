import uuid
from sqlalchemy.orm import Session
from app.models import Topic, Script, Video, Task
from app.agents.asset_generation_agent import _parse_shots, run_asset_generation
from app.agents.topic_research_agent import run_topic_research
from app.agents.script_writing_agent import run_script_writing
from app.agents.video_planning_agent import run_video_planning
from app.agents.narration_agent import run_narration
from app.agents.assembly_agent import run_assembly

ASSET_BATCH_SIZE = 5

# Higher number = done first. Finishing videos already in progress
# takes priority over starting brand new topics.
AGENT_PRIORITY = {
    "assembly": 50,
    "narration": 40,
    "asset_generation": 30,
    "video_planning": 20,
    "script_writing": 10,
    "topic_research": 1,
}


def _has_open_task(db: Session, agent_name: str, key: str, value: str) -> bool:
    """True if a pending/running task already exists for this exact step."""
    tasks = db.query(Task).filter(
        Task.agent_name == agent_name,
        Task.status.in_(["pending", "running"]),
    ).all()
    for t in tasks:
        if (t.payload or {}).get(key) == value:
            return True
    return False


def _last_task_failed(db: Session, agent_name: str, key: str, value: str) -> bool:
    """True if the MOST RECENT attempt at this exact step failed.
    This stops the Supervisor from retrying something broken every 20 minutes —
    a failed step is left alone until a human requeues it."""
    tasks = db.query(Task).filter(Task.agent_name == agent_name).order_by(Task.created_at.desc()).all()
    for t in tasks:
        if (t.payload or {}).get(key) == value:
            return t.status == "failed"
    return False


def _queue_task(db: Session, title: str, agent_name: str, payload: dict):
    task = Task(
        title=title,
        agent_name=agent_name,
        status="pending",
        priority=AGENT_PRIORITY.get(agent_name, 0),
        payload=payload,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def plan_next_steps(db: Session) -> list[dict]:
    """Check every topic/script/video and queue up whatever step it needs next,
    unless that step is already queued, running, or failed last time."""
    queued = []

    # Topics with no script yet -> queue script_writing
    topics = db.query(Topic).filter(Topic.status == "research").all()
    for topic in topics:
        if db.query(Script).filter(Script.topic_id == topic.id).first():
            continue
        key, value = "topic_id", str(topic.id)
        if _has_open_task(db, "script_writing", key, value) or _last_task_failed(db, "script_writing", key, value):
            continue
        t = _queue_task(db, f"Write script for: {topic.title}", "script_writing", {"topic_id": value})
        queued.append({"agent": "script_writing", "task_id": str(t.id)})

    # Scripts with no video yet -> queue video_planning
    scripts = db.query(Script).all()
    for script in scripts:
        if db.query(Video).filter(Video.script_id == script.id).first():
            continue
        key, value = "script_id", str(script.id)
        if _has_open_task(db, "video_planning", key, value) or _last_task_failed(db, "video_planning", key, value):
            continue
        t = _queue_task(db, f"Plan video for: {script.title}", "video_planning", {"script_id": value})
        queued.append({"agent": "video_planning", "task_id": str(t.id)})

    #
