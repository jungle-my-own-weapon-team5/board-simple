from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.admin import DiscussionTopicRefreshRequest, DiscussionTopicUpdate, ThumbnailPreviewRequest, ThumbnailPreviewResponse
from app.schemas.ai import DiscussionTopic
from app.services.discussion_topics import (
    list_admin_discussion_topics,
    refresh_discussion_topics,
    update_discussion_topic,
)
from app.services.mcp_server import generate_thumbnail_for_post

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/thumbnail/preview", response_model=ThumbnailPreviewResponse)
def preview_thumbnail(
    payload: ThumbnailPreviewRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_admin_user),
) -> ThumbnailPreviewResponse:
    result = generate_thumbnail_for_post(
        db,
        settings,
        payload.title,
        payload.content,
        payload.category,
        payload.tags,
    )
    structured = result["structuredContent"]
    return ThumbnailPreviewResponse.model_validate(structured)


@router.get("/discussion-topics", response_model=list[DiscussionTopic])
def admin_list_discussion_topics(
    topic_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_admin_user),
) -> list[DiscussionTopic]:
    return list_admin_discussion_topics(db, settings, topic_date)


@router.post("/discussion-topics/refresh", response_model=list[DiscussionTopic])
def admin_refresh_discussion_topics(
    payload: DiscussionTopicRefreshRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_admin_user),
) -> list[DiscussionTopic]:
    return refresh_discussion_topics(db, settings, payload.topic_date)


@router.patch("/discussion-topics/{topic_id}", response_model=DiscussionTopic)
def admin_update_discussion_topic(
    topic_id: int,
    payload: DiscussionTopicUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> DiscussionTopic:
    try:
        return update_discussion_topic(db, topic_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
