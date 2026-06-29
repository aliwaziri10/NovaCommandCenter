import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# User
class UserBase(BaseSchema):
    email: EmailStr
    name: str
    role: str = "viewer"
    is_active: bool = True


class UserCreate(UserBase):
    pass


class UserUpdate(BaseSchema):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Topic
class TopicBase(BaseSchema):
    title: str
    category: str
    trend_score: float = 0.0
    status: str = "research"
    notes: Optional[str] = None


class TopicCreate(TopicBase):
    pass


class TopicUpdate(BaseSchema):
    title: Optional[str] = None
    category: Optional[str] = None
    trend_score: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class TopicResponse(TopicBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Script
class ScriptBase(BaseSchema):
    title: str
    content: str = ""
    status: str = "draft"
    topic_id: Optional[uuid.UUID] = None


class ScriptCreate(ScriptBase):
    pass


class ScriptUpdate(BaseSchema):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    topic_id: Optional[uuid.UUID] = None


class ScriptResponse(ScriptBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Video
class VideoBase(BaseSchema):
    title: str
    status: str = "planned"
    views: int = 0
    topic_id: Optional[uuid.UUID] = None
    script_id: Optional[uuid.UUID] = None


class VideoCreate(VideoBase):
    pass


class VideoUpdate(BaseSchema):
    title: Optional[str] = None
    status: Optional[str] = None
    views: Optional[int] = None
    topic_id: Optional[uuid.UUID] = None
    script_id: Optional[uuid.UUID] = None


class VideoResponse(VideoBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Short
class ShortBase(BaseSchema):
    title: str
    platform: str = "youtube"
    status: str = "draft"
    views: int = 0
    video_id: Optional[uuid.UUID] = None


class ShortCreate(ShortBase):
    pass


class ShortUpdate(BaseSchema):
    title: Optional[str] = None
    platform: Optional[str] = None
    status: Optional[str] = None
    views: Optional[int] = None
    video_id: Optional[uuid.UUID] = None


class ShortResponse(ShortBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Sponsor
class SponsorBase(BaseSchema):
    name: str
    contact_email: EmailStr
    tier: str = "bronze"
    status: str = "active"


class SponsorCreate(SponsorBase):
    pass


class SponsorUpdate(BaseSchema):
    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    tier: Optional[str] = None
    status: Optional[str] = None


class SponsorResponse(SponsorBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Revenue
class RevenueBase(BaseSchema):
    amount: float
    type: str = "sponsor"
    date: date
    sponsor_id: Optional[uuid.UUID] = None


class RevenueCreate(RevenueBase):
    pass


class RevenueUpdate(BaseSchema):
    amount: Optional[float] = None
    type: Optional[str] = None
    date: Optional[date] = None
    sponsor_id: Optional[uuid.UUID] = None


class RevenueResponse(RevenueBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Task
class TaskBase(BaseSchema):
    title: str
    agent_name: str
    status: str = "pending"
    priority: int = 1
    payload: Optional[dict[str, Any]] = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseSchema):
    title: Optional[str] = None
    agent_name: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    payload: Optional[dict[str, Any]] = None


class TaskResponse(TaskBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# Dashboard
class PipelineCounts(BaseSchema):
    scripts: int
    videos: int
    shorts: int
    published_videos: int
    published_shorts: int


class AgentSummary(BaseSchema):
    agent_name: str
    pending: int
    running: int
    completed: int
    failed: int


class CEODashboardResponse(BaseSchema):
    total_revenue: float
    active_topics: int
    pipeline: PipelineCounts
    agents: list[AgentSummary]
    top_topics: list[TopicResponse]
    revenue_trend: list[dict[str, Any]]


class KPIDashboardResponse(BaseSchema):
    total_views: int
    total_revenue: float
    total_subscribers: int
    conversion_rate: float
    weekly_stats: list[dict[str, Any]]
    platform_breakdown: list[dict[str, Any]]


class PipelineItem(BaseSchema):
    script: Optional[ScriptResponse] = None
    video: Optional[VideoResponse] = None
    shorts: list[ShortResponse] = Field(default_factory=list)


class ContentPipelineResponse(BaseSchema):
    items: list[PipelineItem]


class RevenueSummaryResponse(BaseSchema):
    monthly_totals: list[dict[str, Any]]
    by_sponsor: list[dict[str, Any]]
    by_type: list[dict[str, Any]]


class AgentTasksResponse(BaseSchema):
    agents: list[AgentSummary]
    tasks: list[TaskResponse]
