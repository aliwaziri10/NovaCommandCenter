import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Uuid, func, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="planned")
    views: Mapped[int] = mapped_column(Integer, default=0)
    production_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asset_urls: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    clip_urls: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    audio_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    youtube_video_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shot_durations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # ADDED (2026-08-03): ported from Marius's continuity-anchoring fix. Stores
    # a single reference image (generated once per video, before shot 0) that
    # every shot's Agnes call anchors to - either directly (shot 0) or via the
    # previous shot's own last frame (every shot after). This is what gives
    # Nova character/scene consistency across cuts, which it previously had
    # zero mechanism for (pure blind text-to-video on every shot).
    character_reference_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # ADDED (2026-09-02): True once cinematographer_agent.py has enriched
    # this video's production_plan with a full DP-style shot-composition
    # brief per shot (framing, lighting, blocking, lens feel). Gates
    # video_clips so Agnes never generates from a plan that hasn't been
    # through this pass yet - see supervisor_agent.py's _find_next_task.
    cinematography_done: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    topic_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    script_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    topic = relationship("Topic", back_populates="videos")
    script = relationship("Script", back_populates="videos")
    shorts = relationship("Short", back_populates="video")
