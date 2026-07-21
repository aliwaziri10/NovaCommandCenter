import json
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import Topic, Script, Video, Task
from app.agents.topic_research_agent import run_topic_research
from app.agents.script_writing_agent import run_script_writing
from app.agents.video_planning_agent import run_video_planning
from app.agents.asset_generation_agent import _parse_shots
from app.agents.github_actions_client import trigger_workflow
# NOTE: run_assembly (Railway-native) is intentionally no longer imported/called —
# assembly now runs via the assemble.yml GitHub Actions workflow instead, same
# pattern as video_clips, to avoid crashing Railway's 512MB RAM stitching real clips.
#
# NOTE (2026-07-19): asset_generation (Pollinations.ai still images) has been
# removed from the pipeline entirely. Audit found the images it produced were
# never used anywhere downstream — video_clips generates real clips straight
# from each shot's text description via Agnes, and assembly only ever reads
# clip_urls (assemble.py explicitly treats asset_urls as "reference only" and
# never uses them). asset_generation was a pure gate: narration, video_clips,
# and assembly all refused to proceed until it fully finished, and Pollinations'
# free tier was failing with HTTP 500s often enough that videos stalled forever
# waiting on images nothing downstream reads. Removing the gate unblocks the
# real pipeline. run_asset_generation/_parse_shots import kept only for shot
# counting; the agent function itself is no longer called.
#
# NOTE (2026-07-21): narration switched from the in-process run_narration()
# (backend/app/agents/narration_agent.py — gTTS, writes to local Render disk)
# to the narrate.yml GitHub Actions workflow (.github/scripts/narrate.py —
# Kokoro TTS, uploads via the backend's upload endpoint to Supabase Storage).
# Render's disk is ephemeral like Railway's was: run_narration wrote a local
# path into video.audio_path, and once Render recycled the instance the file
# was gone and audio_path was left pointing nowhere. narrate.yml persists the
# audio to Supabase Storage the same way video_clips/assembly already do for
# their outputs, so it survives restarts. run_narration/narration_agent.py is
# no longer called by the supervisor and is now dead code (kept in the repo
# in case anything else references it).
#
# NOTE (2026-07-21b): the active-videos query below previously only excluded
# status "assembled", not "uploaded". That let already-uploaded videos (like
# 424a809e, fully on YouTube) get re-selected by the assembly stage forever —
# their narration file had since been cleaned up from Supabase Storage, so
# every re-trigger of assemble.yml failed with a 400 fetching it. "uploaded"
# is now excluded too so finished videos stop being reprocessed.

MAX_RETRIES = 2
MIN_TOPICS_IN_PIPELINE = 3
STALE_TASK_MINUTES = 30
CLIP_COOLDOWN_MINUTES = 25  # a 3-shot Agnes batch takes roughly 10-20 min; avoid re-triggering mid-run
ASSEMBLY_COOLDOWN_MINUTES = 35  # assemble.yml has timeout-minutes: 30; give a 5-min safety margin before re-trigger
NARRATION_COOLDOWN_MINUTES = 20  # narrate.yml has timeout-minutes: 15; give a 5-min safety margin before re-trigger
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


def _has_recent_task(db, agent_name, id_key, id_value, minutes):
    """Unlike _has_active_task, this checks ANY task (regardless of status)
    created within the cooldown window. Used for fire-and-forget GitHub Actions
    triggers, where we have no visibility into whether the run is still going."""
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


def _find_next_task(db):
    videos = db.query(Video).filter(Video.status.notin_(["assembled", "uploaded"])).all()

    # Stage: assembly (needs narration audio + all clips done)
    for video in videos:
        if not video.production_plan or not video.audio_path:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if not total_shots:
            continue
        clip_urls = video.clip_urls or []
        clips_done = len([u for u in clip_urls if u])
        if clips_done < total_shots:
            continue  # clips not finished yet — handled by the video_clips stage below
        vid = str(video.id)
        # Fire-and-forget like video_clips: use recency cooldown, not active-status check,
        # since we have no visibility into whether assemble.yml is still running.
        if _has_recent_task(db, "assembly", "video_id", vid, ASSEMBLY_COOLDOWN_MINUTES):
            continue
        if _failed_attempts(db, "assembly", "video_id", vid) >= MAX_RETRIES:
            continue
        return {"agent_name": "assembly", "payload": {"video_id": vid}, "title": "Assemble video " + vid[:8]}

    # Stage: video_clips (needs narration audio; clips not yet complete)
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
        return {
            "agent_name": "video_clips",
            "payload": {"video_id": vid},
            "title": "Generate video clips for " + vid[:8] + " (" + str(clips_done) + "/" + str(total_shots) + ")",
        }

    # Stage: narration (needs production_plan; no longer waits on asset_generation).
    # Fire-and-forget via narrate.yml GitHub Actions workflow — same cooldown pattern
    # as video_clips/assembly, since we have no visibility into whether the run
    # is still going.
    for video in videos:
        if not video.production_plan or video.audio_path:
            continue
        total_shots = len(_parse_shots(video.production_plan))
        if not total_shots:
            continue
        vid = str(video.id)
        if _has_recent_task(db, "narration", "video_id", vid, NARRATION_COOLDOWN_MINUTES):
            continue
        return {"agent_name": "narration", "payload": {"video_id": vid}, "title": "Narrate video " + vid[:8]}

    # Stage: video_planning
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

    # Stage: script_writing
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

    # Stage: topic_research
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
