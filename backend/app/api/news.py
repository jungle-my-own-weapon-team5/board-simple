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
    DuplicateMatch,
    HackerNewsCreatedPost,
    HackerNewsImportRequest,
    HackerNewsImportResponse,
    HackerNewsPreviewRequest,
    HackerNewsPreviewResponse,
    HackerNewsSkippedItem,
    NewsDuplicateJudgementRequest,
    NewsDuplicateJudgementResponse,
    WebArticleCreatedPost,
    WebArticleImportRequest,
    WebArticleImportResponse,
    WebArticlePreviewRequest,
    WebArticlePreviewResponse,
    WebArticleSkippedItem,
)
from app.services.duplicate_check import DuplicateCheckService, get_duplicate_check_service
from app.services.duplicate_judgement import (
    DuplicateJudgementService,
    get_duplicate_judgement_service,
)
from app.services.hacker_news import (
    HackerNewsService,
    build_hacker_news_post_content,
    get_hacker_news_service,
    truncate_title,
)
from app.services.news_curation import (
    NewsCurationService,
    build_web_article_post_content,
    get_news_curation_service,
)
from app.services.rag import sync_post_index
from app.services.tags import extract_tag_names, get_or_create_tags

router = APIRouter(prefix="/news", tags=["news"])
logger = logging.getLogger(__name__)


def get_hacker_news_service_dependency() -> HackerNewsService:
    return get_hacker_news_service()


def get_duplicate_check_service_dependency() -> DuplicateCheckService:
    return get_duplicate_check_service()


def get_news_curation_service_dependency() -> NewsCurationService:
    return get_news_curation_service()


def get_duplicate_judgement_service_dependency() -> DuplicateJudgementService:
    return get_duplicate_judgement_service()


@router.post("/hacker-news/preview", response_model=HackerNewsPreviewResponse)
def preview_hacker_news(
    payload: HackerNewsPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: HackerNewsService = Depends(get_hacker_news_service_dependency),
    duplicate_service: DuplicateCheckService = Depends(get_duplicate_check_service_dependency),
) -> HackerNewsPreviewResponse:
    _ = current_user
    items = service.preview(db, payload.source, payload.query, payload.limit)
    payload_items = []
    for item in items:
        data = item.__dict__.copy()
        matches = duplicate_service.check(
            db,
            title=item.title,
            url=item.url,
            content=item.summary,
        )
        data["duplicate_matches"] = _duplicate_matches(matches)
        payload_items.append(data)
    return HackerNewsPreviewResponse(
        items=payload_items,
    )


@router.post("/web/preview", response_model=WebArticlePreviewResponse)
def preview_web_article(
    payload: WebArticlePreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: NewsCurationService = Depends(get_news_curation_service_dependency),
    duplicate_service: DuplicateCheckService = Depends(get_duplicate_check_service_dependency),
) -> WebArticlePreviewResponse:
    _ = current_user
    provisional_title = payload.url.rsplit("/", 1)[-1] or payload.url
    matches = duplicate_service.check(
        db,
        title=provisional_title,
        url=payload.url,
        content=payload.article_text,
    )
    item = service.preview_web_article(payload.url, matches, payload.article_text)
    if item.summary_status == "success":
        item.duplicate_matches = duplicate_service.check(
            db,
            title=item.title,
            url=item.url,
            content=item.summary,
        )
    return WebArticlePreviewResponse(
        item={
            **item.__dict__,
            "duplicate_matches": _duplicate_matches(item.duplicate_matches),
        }
    )


@router.post("/duplicates/judge", response_model=NewsDuplicateJudgementResponse)
def judge_news_duplicates(
    payload: NewsDuplicateJudgementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: DuplicateJudgementService = Depends(get_duplicate_judgement_service_dependency),
) -> NewsDuplicateJudgementResponse:
    _ = current_user
    return NewsDuplicateJudgementResponse(items=service.judge(db, payload.items))


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


@router.post("/web/import", response_model=WebArticleImportResponse)
def import_web_articles(
    payload: WebArticleImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebArticleImportResponse:
    created: list[WebArticleCreatedPost] = []
    skipped: list[WebArticleSkippedItem] = []

    for item in payload.items:
        exists = db.scalar(
            select(Post.id).where(
                Post.source_type == "web_article",
                Post.source_id == item.source_id,
            )
        )
        if exists is not None:
            skipped.append(WebArticleSkippedItem(source_id=item.source_id, reason="already_imported"))
            continue

        content = build_web_article_post_content(item.summary, item.key_points, item.url)
        post = Post(
            title=truncate_title(item.title),
            content=content,
            author_id=current_user.id,
            source_type="web_article",
            source_id=item.source_id,
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
            logger.exception("Failed to index imported web article", extra={"post_id": post.id})
            db.rollback()
        created.append(
            WebArticleCreatedPost(
                post_id=post.id,
                source_id=item.source_id,
                title=post.title,
            )
        )

    return WebArticleImportResponse(created=created, skipped=skipped)


def _duplicate_matches(matches: list) -> list[DuplicateMatch]:
    return [
        DuplicateMatch(
            post_id=match.post_id,
            title=match.title,
            reason=match.reason,
            score=match.score,
        )
        for match in matches
    ]
