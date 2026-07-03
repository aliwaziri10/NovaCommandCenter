from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import engine, Base
from app.routers.crud_factory import make_crud_router
from app.routers import dashboard, content, revenue_router, tasks_router, download_router
from app.models import User, Topic, Script, Video, Short, Sponsor, Revenue, Task
from app.schemas import (
    UserCreate, UserUpdate, UserResponse,
    TopicCreate, TopicUpdate, TopicResponse,
    ScriptCreate, ScriptUpdate, ScriptResponse,
    VideoCreate, VideoUpdate, VideoResponse,
    ShortCreate, ShortUpdate, ShortResponse,
    SponsorCreate, SponsorUpdate, SponsorResponse,
    RevenueCreate, RevenueUpdate, RevenueResponse,
    TaskCreate, TaskUpdate, TaskResponse,
)
app = FastAPI(title="Nova Command Center API", version="1.0.0")
Base.metadata.create_all(bind=engine)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
@app.get("/health")
def health_check():
    return {"status": "healthy"}
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(content.router, prefix="/api/v1")
app.include_router(revenue_router.router, prefix="/api/v1")
app.include_router(tasks_router.router, prefix="/api/v1")
app.include_router(download_router.router, prefix="/api/v1")
crud_routers = [
    make_crud_router("/users", User, UserResponse, UserCreate, UserUpdate, "users"),
    make_crud_router("/topics", Topic, TopicResponse, TopicCreate, TopicUpdate, "topics"),
    make_crud_router("/scripts", Script, ScriptResponse, ScriptCreate, ScriptUpdate, "scripts"),
    make_crud_router("/videos", Video, VideoResponse, VideoCreate, VideoUpdate, "videos"),
    make_crud_router("/shorts", Short, ShortResponse, ShortCreate, ShortUpdate, "shorts"),
    make_crud_router("/sponsors", Sponsor, SponsorResponse, SponsorCreate, SponsorUpdate, "sponsors"),
    make_crud_router("/revenue", Revenue, RevenueResponse, RevenueCreate, RevenueUpdate, "revenue"),
    make_crud_router("/tasks", Task, TaskResponse, TaskCreate, TaskUpdate, "tasks"),
]
for r in crud_routers:
    app.include_router(r, prefix="/api/v1")
