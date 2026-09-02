import os
import sqlite3

from fastapi import APIRouter
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/admin", tags=["admin"])

TABLES = ["users", "topics", "scripts", "videos", "shorts", "revenue", "sponsors", "tasks"]

EXACT_CANDIDATES = [
    "/app/data/nova.db",
    "/data/nova.db",
    "/app/nova.db",
    "./data/nova.db",
]


@router.get("/dump-sqlite")
def dump_sqlite():
    found = None
    for p in EXACT_CANDIDATES:
        if os.path.isfile(p):
            found = p
            break

    if not found:
        listing = {}
        for d in ["/app", "/app/data", "/data"]:
            if os.path.isdir(d):
                try:
                    listing[d] = os.listdir(d)
                except Exception as e:
                    listing[d] = f"error: {e}"
            else:
                listing[d] = "does not exist"
        return {"error": "no .db file found at known paths", "checked": EXACT_CANDIDATES, "directory_listing": listing}

    conn = sqlite3.connect(found)
    conn.row_factory = sqlite3.Row
    data = {}
    for t in TABLES:
        try:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
            data[t] = [dict(r) for r in rows]
        except Exception as e:
            data[t] = f"error reading table: {e}"
    conn.close()
    return {"sqlite_path": found, "tables": data}


@router.get("/add-shot-durations-column")
def add_shot_durations_column():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS shot_durations JSON"))
    return {"status": "ok", "message": "shot_durations column present on videos table"}


# ADDED (2026-09-02): supports the new cinematographer_agent.py stage,
# which runs between video_planning and video_clips to enrich each shot's
# production_plan text with a full DP-style shot-composition brief
# (framing, lighting, blocking, lens feel) before Agnes ever sees it.
# This boolean tracks whether a given video's production_plan has already
# been through that enrichment pass, so the supervisor doesn't re-run it
# every cycle and so video_clips can gate on it (see supervisor_agent.py's
# AGENT_ID_KEY / _find_next_task changes in the same rollout).
@router.get("/add-cinematography-done-column")
def add_cinematography_done_column():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE videos ADD COLUMN IF NOT EXISTS cinematography_done BOOLEAN DEFAULT FALSE"))
    return {"status": "ok", "message": "cinematography_done column present on videos table"}
