from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.comment import Comment


def get_comment_with_author(db: Session, comment_id: int) -> Comment | None:
    return db.scalar(
        select(Comment)
        .where(Comment.id == comment_id)
        .options(selectinload(Comment.author))
    )


def count_comments_by_post(db: Session, post_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Comment).where(Comment.post_id == post_id)
        )
        or 0
    )


def list_comments_by_post(
    db: Session, post_id: int, offset: int, limit: int
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


def add_comment(db: Session, comment: Comment) -> None:
    db.add(comment)


def delete_comment(db: Session, comment: Comment) -> None:
    db.delete(comment)
