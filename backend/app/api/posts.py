from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.post import Post
from app.models.user import User
from app.schemas.post import (
    PostCreate,
    PostDuplicateCheckRequest,
    PostDuplicateCheckResponse,
    PostListItem,
    PostPage,
    PostRead,
    PostThumbnailRequest,
    PostThumbnailResponse,
    PostUpdate,
)
from app.services import posts as post_service
from app.services.errors import NotFoundError, PermissionDeniedError

router = APIRouter(prefix="/posts", tags=["posts"])


def _raise_post_http_error(exc: NotFoundError | PermissionDeniedError) -> None:
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    raise HTTPException(status_code=403, detail=exc.detail) from exc


@router.get("", response_model=PostPage)
def list_posts(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    q: str | None = Query(default=None),
    content_q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PostPage:
    posts, total = post_service.list_posts(
        db,
        page=page,
        size=size,
        q=q,
        content_q=content_q,
        tag=tag,
    )
    return PostPage(
        items=[PostListItem.model_validate(post) for post in posts],
        total=total,
        page=page,
        size=size,
    )


@router.post("/duplicate-check", response_model=PostDuplicateCheckResponse)
def check_duplicate_posts(
    payload: PostDuplicateCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostDuplicateCheckResponse:
    return PostDuplicateCheckResponse(
        items=post_service.check_duplicate_posts(
            db,
            title=payload.title,
            content=payload.content,
            tags=payload.tags,
            exclude_post_id=payload.exclude_post_id,
        )
    )


@router.post("/generate-thumbnail", response_model=PostThumbnailResponse)
def generate_thumbnail(
    payload: PostThumbnailRequest,
    current_user: User = Depends(get_current_user),
) -> PostThumbnailResponse:
    try:
        return post_service.generate_thumbnail_markdown(payload)
    except post_service.ThumbnailNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI image generation is not configured.",
        ) from exc
    except post_service.ThumbnailGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Thumbnail image generation failed.",
        ) from exc


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Post:
    return post_service.create_post(db, payload, current_user)


@router.get("/{post_id}", response_model=PostRead)
def read_post(post_id: int, db: Session = Depends(get_db)) -> Post:
    try:
        return post_service.get_post(db, post_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc


@router.put("/{post_id}", response_model=PostRead)
def update_post(
    post_id: int,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Post:
    try:
        return post_service.update_post(db, post_id, payload, current_user)
    except (NotFoundError, PermissionDeniedError) as exc:
        _raise_post_http_error(exc)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        post_service.delete_post(db, post_id, current_user)
    except (NotFoundError, PermissionDeniedError) as exc:
        _raise_post_http_error(exc)
