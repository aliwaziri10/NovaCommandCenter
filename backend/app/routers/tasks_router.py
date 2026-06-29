import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task
from app.schemas import AgentSummary, AgentTasksResponse, TaskResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


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
    db.refresh(task)
    return task
