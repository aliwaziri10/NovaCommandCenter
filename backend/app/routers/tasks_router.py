import uuid
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Task
from app.schemas import AgentSummary, AgentTasksResponse, TaskResponse
from app.agents.topic_research_agent import run_topic_research
from app.agents.script_writing_agent import run_script_writing

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
        if agent == "topic_research":
            category = (task.payload or {}).get("category", "History")
            result = run_topic_research(db, category=category)
            task.status = "completed"
            task.payload = {**(task.payload or {}), "result": result}
        elif agent == "script_writing":
            topic_id = (task.payload or {})["topic_id"]
            result = run_script_writing(db, topic_id=topic_id)
            task.status = "completed"
            task.payload = {**(task.payload or {}), "result": result}
        else:
            task.status = "completed"
        db.commit()
        db.refresh(task)
    except Exception as e:
        task.status = "failed"
        task.payload = {**(task.payload or {}), "error": str(e)}
        db.commit()
        db.refresh(task)
    return task
