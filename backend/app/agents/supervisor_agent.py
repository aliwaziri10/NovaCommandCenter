import json
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import Topic, Script, Video, Task
from app.agents.topic_research_agent import run_topic_research
from app.agents.script_writing_agent import run_script_writing
from app.agents.video_planning_agent import run_video_planning
from app.agents.asset_generation_agent import _parse_shots
from app.agents.github_actions_client import trigger_workflow, open_issue
from app.agents.strategy_research_agent import run_strategy_research

MAX_RETRIES = 2
MIN_TOPICS_IN_PIPELINE = 3
STALE_TASK_MINUTES = 30
CLIP_COOLDOWN_MINUTES = 25
ASSEMBLY_COOLDOWN_MINUTES = 35
NARRATION_COOLDOWN_MINUTES = 20
STRATEGY_RESEARCH_COOLDOWN_MINUTES = 7 * 24 * 60
VIDEO_PLANNING_STARVATION_MINUTES = 90
LOG_PATH = "/app/data/supervisor_log.json"


def _clear_stale_tasks(db):
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


def _has_recent_task(db, agent_name, id_key, id_value, minutes):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    tasks = db.query(Task).filter(
        Task.agent_name == agent_name,
        Task.created_at >= cutoff,
    ).all()
    for t in tasks:
        payload = t.payload or {}
        if str(payload.get(id_key)) == str(id_value):
            return True
    return False


# ADDED (2026-08-28): the id_key used for each agent's payload, so the
# generic abandonment-alert code below can look up the right identifier
# without a big if/elif chain duplicated from _find_next_task. Keys must
# match exactly what _execute()/each return statement in _find_next_task
# already puts in payload for that agent_name.
AGENT_ID_KEY = {
    "assembly": "video_id",
    "video_clips": "video_id",
    "narration": "video_id",
    "video_planning": "script_id",
    "script_writing": "topic_id",
    "topic_research": "category",
    "strategy_research": "scope",
}


def _find_starved_video_planning_task(db):
    """ADDED (2026-09-02): fix for verified priority-starvation bug.

    _find_next_task() below checks assembly, then video_clips, then
    narration - all looping over in-flight videos - before it ever
    looks at video_planning. As long as even one video is mid-pipeline,
    video_planning never gets a turn, no matter how long a script has
    been sitting there with no video. This starves any script waiting
    on video_planning indefinitely whenever the pipeline has ongoing
    video work, which is most of the time.

    This function is checked FIRST, before the video loops, but only
    returns a task if a script has been waiting at least
    VIDEO_PLANNING_STARVATION_MINUTES with no video, no active task,
    and hasn't exhausted retries - so it doesn't change behavior for
    scripts that are simply next-in-line under normal conditions, only
    for ones that have been genuinely starved.
    """
    scripts = db.query(Script).all()
    cutoff = datetime.utcnow() - timedelta(minutes=VIDEO_PLANNING_STARVATION_MINUTES)
    for script in scripts:
        has_video = db.query(Video).filter(Video.script_id == script.id).first()
        if has_video:
            continue
        if script.created_at is None or script.created_at >= cutoff:
            continue
        sid = str(script.id)
        if _has_active_task(db, "video_planning", "script_id", sid):
            continue
        if _failed_attempts(db, "video_planning", "script_id", sid) >= MAX_RETRIES:
            continue
        return {
            "agent_name": "video_planning",
            "payload": {"script_id": sid},
            "title": "Plan video for script " + sid[:8] + " (starvation override)",
        }
    return None


def _find_next_task(db):
    starved = _find_starved_video_planning_task(db)
    if starved:
        return starved

    videos = db.query(Video).filter(Video.status.notin_(["assembled", "uploaded"])).all()

    for video in videos:
        if not video.production_plan or not video.audio_path:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if not total_shots:
            continue
        clip_urls = video.clip_urls or []
        clips_done = len([u for u in clip_urls if u])
        if clips_done < total_shots:
            continue
        vid = str(video.id)
        if _has_recent_task(db, "assembly", "video_id", vid, ASSEMBLY_COOLDOWN_MINUTES):
            continue
        if _failed_attempts(db, "assembly", "video_id", vid) >= MAX_RETRIES:
            continue
        return {"agent_name": "assembly", "payload": {"video_id": vid}, "title": "Assemble video " + vid[:8]}

    for video in videos:
        if not video.production_plan or not video.audio_path:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if not total_shots:
            continue
        clip_urls = video.clip_urls or []
        clips_done = len([u for u in clip_urls if u])
        if clips_done >= total_shots:
            continue
        vid = str(video.id)
        if _has_recent_task(db, "video_clips", "video_id", vid, CLIP_COOLDOWN_MINUTES):
            continue
        if _failed_attempts(db, "video_clips", "video_id", vid) >= MAX_RETRIES:
            continue
        return {
            "agent_name": "video_clips",
            "payload": {"video_id": vid},
            "title": "Generate video clips for " + vid[:8] + " (" + str(clips_done) + "/" + str(total_shots) + ")",
        }

    for video in videos:
        if not video.production_plan or video.audio_path:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if not total_shots:
            continue
        vid = str(video.id)
        if _has_recent_task(db, "narration", "video_id", vid, NARRATION_COOLDOWN_MINUTES):
            continue
        if _failed_attempts(db, "narration", "video_id", vid) >= MAX_RETRIES:
            continue
        return {"agent_name": "narration", "payload": {"video_id": vid}, "title": "Narrate video " + vid[:8]}

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

    if not _has_recent_task(db, "strategy_research", "scope", "weekly", STRATEGY_RESEARCH_COOLDOWN_MINUTES):
        return {"agent_name": "strategy_research", "payload": {"scope": "weekly"}, "title": "Weekly competitor/self strategy research"}

    return None


def _execute(db, agent_name, payload):
    if agent_name == "topic_research":
        return run_topic_research(db, category=payload.get("category", "History"))
    if agent_name == "script_writing":
        return run_script_writing(db, topic_id=payload["topic_id"])
    if agent_name == "video_planning":
        return run_video_planning(db, script_id=payload["script_id"])
    if agent_name == "narration":
        triggered = trigger_workflow("narrate.yml", {"video_id": payload["video_id"]})
        if not triggered:
            raise RuntimeError("Failed to trigger narrate.yml GitHub Actions workflow.")
        return {"workflow_triggered": True, "video_id": payload["video_id"]}
    if agent_name == "video_clips":
        triggered = trigger_workflow("generate_videos.yml", {"video_id": payload["video_id"]})
        if not triggered:
            raise RuntimeError("Failed to trigger generate_videos.yml GitHub Actions workflow.")
        return {"workflow_triggered": True, "video_id": payload["video_id"]}
    if agent_name == "assembly":
        triggered = trigger_workflow("assemble.yml", {"video_id": payload["video_id"]})
        if not triggered:
            raise RuntimeError("Failed to trigger assemble.yml GitHub Actions workflow.")
        return {"workflow_triggered": True, "video_id": payload["video_id"]}
    if agent_name == "strategy_research":
        return run_strategy_research(db)
    raise ValueError("Unknown agent_name: " + str(agent_name))


def _write_log(entry):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w") as f:
            json.dump(entry, f, default=str)
    except Exception:
        pass


def _maybe_alert_permanent_abandonment(db, agent_name, payload, error_text):
    """ADDED (2026-08-28): fires exactly once, at the moment a given
    (agent_name, id) combination's failure count reaches MAX_RETRIES -
    i.e. the exact cycle where _find_next_task will start silently
    skipping it forever. Before this, that skip was permanent and
    invisible: no issue, no log line anyone would see, nothing. A topic
    could sit half-finished for weeks and nobody would know without
    manually querying failed tasks (this is exactly what happened to
    topic aac24763 on 2026-08-26/27).

    Fires "exactly once" because this only runs from the except-block of
    run_supervisor_cycle right after a failure is recorded, and
    _find_next_task never selects a (agent_name, id) again once its
    failure count >= MAX_RETRIES - so the count can never be observed
    equal to MAX_RETRIES a second time for the same id.

    id_key/id_value are looked up generically via AGENT_ID_KEY rather
    than a per-agent if/elif chain, so adding a new agent to the
    supervisor later can't accidentally skip wiring this up.

    Never raises - a broken alert must not break the supervisor cycle
    itself (same reasoning as open_issue()'s own internal try/except).
    """
    try:
        id_key = AGENT_ID_KEY.get(agent_name)
        if not id_key:
            return
        id_value = payload.get(id_key)
        if id_value is None:
            return

        attempts = _failed_attempts(db, agent_name, id_key, id_value)
        if attempts != MAX_RETRIES:
            return

        title = f"Supervisor gave up: {agent_name} permanently stuck for {id_key}={id_value}"
        body = (
            f"The supervisor has hit MAX_RETRIES ({MAX_RETRIES}) for this "
            f"(agent, id) pair and will now silently skip it forever - "
            f"`_find_next_task` excludes anything at or above MAX_RETRIES "
            f"failed attempts.\n\n"
            f"**Agent:** {agent_name}\n"
            f"**{id_key}:** {id_value}\n"
            f"**Last error:**\n```\n{str(error_text)[:1500]}\n```\n\n"
            f"This will NOT be retried automatically. To unstick it, clear "
            f"the failed `tasks` rows for this {id_key} in Supabase (resets "
            f"the attempt count to 0) once the underlying cause is "
            f"addressed, or investigate why it's failing first."
        )
        open_issue(title, body, labels=["supervisor-abandoned"])
    except Exception as e:
        print(f"WARNING: _maybe_alert_permanent_abandonment itself failed (non-fatal): {type(e).__name__}: {e}")


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
        _maybe_alert_permanent_abandonment(db, next_action["agent_name"], next_action["payload"], str(e))
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
