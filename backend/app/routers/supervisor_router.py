import json
import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.agents.supervisor_agent import run_supervisor_cycle, LOG_PATH

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


@router.get("/status")
def get_supervisor_status():
    if not os.path.exists(LOG_PATH):
        return {"message": "Supervisor has not run yet."}
    with open(LOG_PATH, "r") as f:
        return json.load(f)


@router.post("/run-now")
def trigger_supervisor_run(db: Session = Depends(get_db)):
    return run_supervisor_cycle(db)
