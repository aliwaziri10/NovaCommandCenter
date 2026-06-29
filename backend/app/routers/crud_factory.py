import uuid
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
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

T = TypeVar("T")


def make_crud_router(
    prefix: str,
    model,
    response_schema,
    create_schema,
    update_schema,
    tag: str,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get("", response_model=list[response_schema])
    def list_items(db: Session = Depends(get_db)):
        return db.query(model).order_by(model.created_at.desc()).all()

    @router.get("/{item_id}", response_model=response_schema)
    def get_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
        item = db.query(model).filter(model.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"{tag} not found")
        return item

    @router.post("", response_model=response_schema, status_code=201)
    def create_item(data: create_schema, db: Session = Depends(get_db)):
        item = model(**data.model_dump())
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @router.patch("/{item_id}", response_model=response_schema)
    def update_item(item_id: uuid.UUID, data: update_schema, db: Session = Depends(get_db)):
        item = db.query(model).filter(model.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"{tag} not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        db.commit()
        db.refresh(item)
        return item

    @router.delete("/{item_id}", status_code=204)
    def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
        item = db.query(model).filter(model.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"{tag} not found")
        db.delete(item)
        db.commit()

    return router
