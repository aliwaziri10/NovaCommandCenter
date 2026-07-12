import glob
import sqlite3

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])

TABLES = ["users", "topics", "scripts", "videos", "shorts", "revenue", "sponsors", "tasks"]


@router.get("/dump-sqlite")
def dump_sqlite():
    """Read-only: finds the legacy local SQLite db (if the volume still has
    it) and returns every row from every known table as JSON. Does not
    write anything, does not touch Postgres."""
    candidates = glob.glob("/**/nova.db", recursive=True)
    if not candidates:
        return {"error": "nova.db not found on this container/volume", "hint": "searched recursively from / for nova.db"}

    sqlite_path = candidates[0]
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    data = {}
    for t in TABLES:
        try:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
            data[t] = [dict(r) for r in rows]
        except Exception as e:
            data[t] = f"error reading table: {e}"
    conn.close()
    return {"sqlite_path": sqlite_path, "all_candidates_found": candidates, "tables": data}
