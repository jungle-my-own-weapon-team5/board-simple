from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.post import Post
from app.models.user import User
from app.schemas.news import (
    HackerNewsCreatedPost,
    HackerNewsImportRequest,
    HackerNewsImportResponse,
    HackerNewsPreviewRequest,
    HackerNewsPreviewResponse,
    HackerNewsSkippedItem,
)
from app.services.hacker_news import (
    HackerNewsService,
    build_hacker_news_post_content,
    get_hacker_news_service,
    truncate_title,
)
from app.services.rag import sync_post_index
from app.services.tags import extract_tag_names, get_or_create_tags

router = APIRouter(prefix="/news", tags=["news"])
logger = logging.getLogger(__name__)


def get_hacker_news_service_dependency() -> HackerNewsService:
    return get_hacker_news_service()


@router.post("/hacker-news/preview", response_model=HackerNewsPreviewResponse)
def preview_hacker_news(
    payload: HackerNewsPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: HackerNewsService = Depends(get_hacker_news_service_dependency),
) -> HackerNewsPreviewResponse:
    _ = current_user
    items = service.preview(db, payload.source, payload.query, payload.limit)
    return HackerNewsPreviewResponse(
        items=[item.__dict__ for item in items],
    )


@router.post("/hacker-news/import", response_model=HackerNewsImportResponse)
def import_hacker_news(
    payload: HackerNewsImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HackerNewsImportResponse:
    created: list[HackerNewsCreatedPost] = []
    skipped: list[HackerNewsSkippedItem] = []

    for item in payload.items:
        exists = db.scalar(
            select(Post.id).where(
                Post.source_type == "hacker_news",
                Post.source_id == str(item.hn_id),
            )
        )
        if exists is not None:
            skipped.append(
                HackerNewsSkippedItem(hn_id=item.hn_id, reason="already_imported")
            )
            continue

        content = build_hacker_news_post_content(
            summary=item.summary,
            key_points=item.key_points,
            url=item.url,
            hn_url=item.hn_url,
        )
        post = Post(
            title=truncate_title(item.title),
            content=content,
            author_id=current_user.id,
            source_type="hacker_news",
            source_id=str(item.hn_id),
            source_url=item.url,
            source_title=item.title,
            source_fetched_at=datetime.now(timezone.utc),
        )
        post.tags = get_or_create_tags(db, extract_tag_names(content))
        db.add(post)
        db.commit()
        db.refresh(post)
        try:
            sync_post_index(db, post)
        except Exception:
            logger.exception("Failed to index imported Hacker News post", extra={"post_id": post.id})
            db.rollback()
        created.append(
            HackerNewsCreatedPost(
                post_id=post.id,
                hn_id=item.hn_id,
                title=post.title,
            )
        )

    return HackerNewsImportResponse(created=created, skipped=skipped)
