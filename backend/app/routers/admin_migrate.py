import glob
import os
import sqlite3

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])

TABLES = ["users", "topics", "scripts", "videos", "shorts", "revenue", "sponsors", "tasks"]

SEARCH_ROOTS = ["/app", "/data", "/mnt", "/var/lib/containers"]


@router.get("/dump-sqlite")
def dump_sqlite():
    """Read-only: finds the legacy local SQLite db (if the volume still has
    it) and returns every row from every known table as JSON. Does not
    write anything, does not touch Postgres. Searches only known app/volume
    directories (not the whole filesystem) to avoid hanging."""
    candidates: list[str] = []
    for root in SEARCH_ROOTS:
        if os.path.isdir(root):
            candidates.extend(glob.glob(f"{root}/**/nova.db", recursive=True))
            candidates.extend(glob.glob(f"{root}/**/*.db", recursive=True))

    if not candidates:
        listing = {}
        for root in SEARCH_ROOTS:
            if os.path.isdir(root):
                try:
                    listing[root] = os.listdir(root)
                except Exception as e:
                    listing[root] = f"error: {e}"
            else:
                listing[root] = "does not exist"
        return {"error": "no .db file found", "searched_roots": SEARCH_ROOTS, "directory_listing": listing}

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
