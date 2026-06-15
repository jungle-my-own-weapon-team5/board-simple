from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.comment import Comment


def get_comment(db: Session, comment_id: int) -> Comment | None:
    return db.scalar(
        select(Comment)
        .where(Comment.id == comment_id)
        .options(selectinload(Comment.author))
    )


def count_comments(db: Session, post_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Comment).where(Comment.post_id == post_id)
        )
        or 0
    )


def list_comments(
    db: Session,
    *,
    post_id: int,
    offset: int,
    limit: int,
) -> list[Comment]:
    return list(
        db.scalars(
            select(Comment)
            .where(Comment.post_id == post_id)
            .options(selectinload(Comment.author))
            .order_by(Comment.created_at.asc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


def create_comment(
    db: Session,
    *,
    post_id: int,
    author_id: int,
    content: str,
) -> Comment:
    comment = Comment(post_id=post_id, author_id=author_id, content=content)
    db.add(comment)
    db.flush()
    return comment


def update_comment(comment: Comment, *, content: str) -> Comment:
    comment.content = content
    return comment


def delete_comment(db: Session, comment: Comment) -> None:
    db.delete(comment)
    db.flush()
