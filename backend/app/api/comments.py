from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.comment import Comment
from app.models.post import Post
from app.models.user import User
from app.schemas.comment import CommentCreate, CommentPage, CommentRead, CommentUpdate

router = APIRouter(tags=["comments"])


def get_comment_or_404(db: Session, comment_id: int) -> Comment:
    comment = db.scalar(
        select(Comment)
        .where(Comment.id == comment_id)
        .options(selectinload(Comment.author))
    )
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.get("/posts/{post_id}/comments", response_model=CommentPage)
def list_comments(
    post_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> CommentPage:
    post_exists = db.scalar(select(Post.id).where(Post.id == post_id))
    if post_exists is None:
        raise HTTPException(status_code=404, detail="Post not found")

    total = db.scalar(
        select(func.count()).select_from(Comment).where(Comment.post_id == post_id)
    ) or 0
    comments = db.scalars(
        select(Comment)
        .where(Comment.post_id == post_id)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.asc())
        .offset(offset)
        .limit(limit)
    ).all()
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
    post_exists = db.scalar(select(Post.id).where(Post.id == post_id))
    if post_exists is None:
        raise HTTPException(status_code=404, detail="Post not found")

    comment = Comment(
        post_id=post_id,
        author_id=current_user.id,
        content=payload.content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return get_comment_or_404(db, comment.id)


@router.put("/comments/{comment_id}", response_model=CommentRead)
def update_comment(
    comment_id: int,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Comment:
    comment = get_comment_or_404(db, comment_id)
    if comment.author_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the author can update this comment"
        )

    comment.content = payload.content
    db.commit()
    return get_comment_or_404(db, comment.id)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    comment = get_comment_or_404(db, comment_id)
    if comment.author_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the author can delete this comment"
        )

    db.delete(comment)
    db.commit()
