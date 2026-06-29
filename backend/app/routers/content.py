from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Script, Video, Short
from app.schemas import ContentPipelineResponse, PipelineItem, ScriptResponse, VideoResponse, ShortResponse

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/pipeline", response_model=ContentPipelineResponse)
def get_content_pipeline(db: Session = Depends(get_db)):
    scripts = db.query(Script).options(joinedload(Script.videos).joinedload(Video.shorts)).all()
    items = []

    for script in scripts:
        if script.videos:
            for video in script.videos:
                items.append(PipelineItem(
                    script=ScriptResponse.model_validate(script),
                    video=VideoResponse.model_validate(video),
                    shorts=[ShortResponse.model_validate(s) for s in video.shorts],
                ))
        else:
            items.append(PipelineItem(
                script=ScriptResponse.model_validate(script),
                video=None,
                shorts=[],
            ))

    orphan_videos = (
        db.query(Video)
        .options(joinedload(Video.shorts))
        .filter(Video.script_id.is_(None))
        .all()
    )
    for video in orphan_videos:
        items.append(PipelineItem(
            script=None,
            video=VideoResponse.model_validate(video),
            shorts=[ShortResponse.model_validate(s) for s in video.shorts],
        ))

    orphan_shorts = db.query(Short).filter(Short.video_id.is_(None)).all()
    for short in orphan_shorts:
        items.append(PipelineItem(
            script=None,
            video=None,
            shorts=[ShortResponse.model_validate(short)],
        ))

    return ContentPipelineResponse(items=items)
