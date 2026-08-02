import uuid
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Task
from app.schemas import AgentSummary, AgentTasksResponse, TaskResponse
from app.agents.topic_research_agent import run_topic_research
from app.agents.script_writing_agent import run_script_writing
from app.agents.video_planning_agent import run_video_planning
from app.agents.asset_generation_agent import run_asset_generation
from app.agents.narration_agent import run_narration
from app.agents.assembly_agent import run_assembly
from app.agents.strategy_research_agent import run_strategy_research
from app.agents.github_actions_client import trigger_workflow
router = APIRouter(prefix="/tasks", tags=["tasks"])
def _normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "_")
@router.get("/agents", response_model=AgentTasksResponse)
def get_agent_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.priority.desc(), Task.created_at.desc()).all()
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"pending": 0, "running": 0, "completed": 0, "failed": 0})
    for task in tasks:
        grouped[task.agent_name][task.status] = grouped[task.agent_name].get(task.status, 0) + 1
    agents = [
        AgentSummary(agent_name=name, **counts)
        for name, counts in grouped.items()
    ]
    return AgentTasksResponse(
        agents=agents,
        tasks=[TaskResponse.model_validate(t) for t in tasks],
    )
@router.post("/{task_id}/run", response_model=TaskResponse)
def run_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "running"
    db.commit()
    try:
        agent = _normalize(task.agent_name)
        print(f"DEBUG: agent_name raw={task.agent_name!r} normalized={agent!r}")
        # FIX (2026-08-02): on a successful run, drop any stale "error" key left
        # over from a PREVIOUS failed attempt on this same task row. Previously
        # this only ever added new keys on top of the existing payload dict, so
        # a task that failed once and then succeeded on retry still displayed
        # the old error message forever alongside the real, successful result -
        # exactly what happened on the two video_planning retries after the
        # Pollinations API key was added (both showed "completed" with a real
        # result AND a leftover "Pollinations returned nothing usable" error).
        clean_payload = {k: v for k, v in (task.payload or {}).items() if k != "error"}
        if agent == "topic_research":
            category = (task.payload or {}).get("category", "History")
            result = run_topic_research(db, category=category)
            task.status = "completed"
            task.payload = {**clean_payload, "result": result}
        elif agent == "script_writing":
            topic_id = (task.payload or {})["topic_id"]
            result = run_script_writing(db, topic_id=topic_id)
            task.status = "completed"
            task.payload = {**clean_payload, "result": result}
        elif agent == "video_planning":
            script_id = (task.payload or {})["script_id"]
            result = run_video_planning(db, script_id=script_id)
            task.status = "completed"
            task.payload = {**clean_payload, "result": result}
        elif agent == "asset_generation":
            payload = task.payload or {}
            video_id = payload["video_id"]
            start_shot = payload.get("start_shot", 0)
            count = payload.get("count", 5)
            result = run_asset_generation(db, video_id=video_id, start_shot=start_shot, count=count)
            task.status = "completed"
            task.payload = {**clean_payload, "result": result}
        elif agent == "narration":
            video_id = (task.payload or {})["video_id"]
            result = run_narration(db, video_id=video_id)
            task.status = "completed"
            task.payload = {**clean_payload, "result": result}
        elif agent == "video_clips":
            # FIX (2026-08-02): this branch was missing entirely. Any manual
            # "Run" click on a video_clips task from the dashboard fell through
            # to the else clause below and was marked "completed" without ever
            # triggering generate_videos.yml — identical bug to the old missing
            # strategy_research branch, just for the clip-generation stage.
            video_id = (task.payload or {})["video_id"]
            triggered = trigger_workflow("generate_videos.yml", {"video_id": video_id})
            if not triggered:
                raise RuntimeError("Failed to trigger generate_videos.yml GitHub Actions workflow.")
            task.status = "completed"
            task.payload = {**clean_payload, "result": {"workflow_triggered": True, "video_id": video_id}}
        elif agent == "assembly":
            video_id = (task.payload or {})["video_id"]
            result = run_assembly(db, video_id=video_id)
            task.status = "completed"
            task.payload = {**clean_payload, "result": result}
        elif agent == "strategy_research":
            result = run_strategy_research(db)
            task.status = "completed"
            task.payload = {**clean_payload, "result": result}
        else:
            print(f"DEBUG: no matching branch for agent={agent!r}, falling through to else")
            task.status = "completed"
        db.commit()
        db.refresh(task)
    except Exception as e:
        task.status = "failed"
        task.payload = {**(task.payload or {}), "error": str(e)}
        db.commit()
        db.refresh(task)
    return task
