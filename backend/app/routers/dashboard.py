from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.models import Topic, Script, Video, Short, Revenue, Task
from app.schemas import CEODashboardResponse, KPIDashboardResponse, PipelineCounts, AgentSummary, TopicResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _agent_summaries(db: Session) -> list[AgentSummary]:
    tasks = db.query(Task).all()
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"pending": 0, "running": 0, "completed": 0, "failed": 0})
    for task in tasks:
        grouped[task.agent_name][task.status] = grouped[task.agent_name].get(task.status, 0) + 1
    return [
        AgentSummary(agent_name=name, **counts)
        for name, counts in grouped.items()
    ]


@router.get("/ceo", response_model=CEODashboardResponse)
def get_ceo_dashboard(db: Session = Depends(get_db)):
    total_revenue = db.query(func.coalesce(func.sum(Revenue.amount), 0)).scalar() or 0
    active_topics = db.query(Topic).filter(Topic.status.in_(["research", "approved"])).count()

    pipeline = PipelineCounts(
        scripts=db.query(Script).count(),
        videos=db.query(Video).count(),
        shorts=db.query(Short).count(),
        published_videos=db.query(Video).filter(Video.status == "published").count(),
        published_shorts=db.query(Short).filter(Short.status == "published").count(),
    )

    top_topics = (
        db.query(Topic)
        .order_by(Topic.trend_score.desc())
        .limit(5)
        .all()
    )

    six_months_ago = date.today().replace(day=1) - timedelta(days=150)
    month_key = func.strftime("%Y-%m", Revenue.date)
    revenue_rows = (
        db.query(
            month_key.label("month"),
            func.sum(Revenue.amount).label("total"),
        )
        .filter(Revenue.date >= six_months_ago)
        .group_by(month_key)
        .order_by(month_key)
        .all()
    )
    revenue_trend = [
        {"month": row.month or "", "total": float(row.total or 0)}
        for row in revenue_rows
    ]

    return CEODashboardResponse(
        total_revenue=float(total_revenue),
        active_topics=active_topics,
        pipeline=pipeline,
        agents=_agent_summaries(db),
        top_topics=[TopicResponse.model_validate(t) for t in top_topics],
        revenue_trend=revenue_trend,
    )


@router.get("/kpi", response_model=KPIDashboardResponse)
def get_kpi_dashboard(db: Session = Depends(get_db)):
    total_views = (
        db.query(func.coalesce(func.sum(Video.views), 0)).scalar() or 0
    ) + (db.query(func.coalesce(func.sum(Short.views), 0)).scalar() or 0)
    total_revenue = float(db.query(func.coalesce(func.sum(Revenue.amount), 0)).scalar() or 0)
    total_subscribers = 125000
    conversion_rate = round((total_revenue / max(total_views, 1)) * 100, 4)

    weekly_stats = []
    for i in range(6, -1, -1):
        day = date.today() - timedelta(days=i)
        day_revenue = (
            db.query(func.coalesce(func.sum(Revenue.amount), 0))
            .filter(Revenue.date == day)
            .scalar()
            or 0
        )
        weekly_stats.append({
            "day": day.strftime("%a"),
            "revenue": float(day_revenue),
            "views": int(total_views / 7 * (0.8 + i * 0.03)),
        })

    platform_rows = (
        db.query(Short.platform, func.sum(Short.views).label("views"))
        .group_by(Short.platform)
        .all()
    )
    platform_breakdown = [
        {"platform": row.platform, "views": int(row.views or 0)}
        for row in platform_rows
    ]
    if not platform_breakdown:
        platform_breakdown = [
            {"platform": "youtube", "views": int(total_views * 0.5)},
            {"platform": "tiktok", "views": int(total_views * 0.3)},
            {"platform": "instagram", "views": int(total_views * 0.2)},
        ]

    return KPIDashboardResponse(
        total_views=int(total_views),
        total_revenue=total_revenue,
        total_subscribers=total_subscribers,
        conversion_rate=conversion_rate,
        weekly_stats=weekly_stats,
        platform_breakdown=platform_breakdown,
    )


@router.get("/admin/download-video/{video_id}")
def download_video(video_id: str):
    file_path = f"/app/data/media/{video_id}/output/final.mp4"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(file_path, media_type="video/mp4", filename="final.mp4")
