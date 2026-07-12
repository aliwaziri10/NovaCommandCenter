import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Uuid, func
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
    youtube_video_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
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
