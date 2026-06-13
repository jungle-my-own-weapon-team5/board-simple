from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.comment import Comment
from app.models.user import User
from app.schemas.comment import CommentCreate, CommentPage, CommentRead, CommentUpdate
from app.services import comments as comment_service

router = APIRouter(tags=["comments"])


@router.get("/posts/{post_id}/comments", response_model=CommentPage)
def list_comments(
    post_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> CommentPage:
    comments, total = comment_service.list_comments(db, post_id, offset, limit)
    return CommentPage(
        items=[CommentRead.model_validate(comment) for comment in comments],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/posts/{post_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    post_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Comment:
    return comment_service.create_comment(db, post_id, payload, current_user)


@router.put("/comments/{comment_id}", response_model=CommentRead)
def update_comment(
    comment_id: int,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Comment:
    return comment_service.update_comment(db, comment_id, payload, current_user)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    comment_service.delete_comment(db, comment_id, current_user)
