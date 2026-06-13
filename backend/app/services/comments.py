from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.comment import Comment
from app.models.user import User
from app.repositories import comments as comment_repository
from app.repositories import posts as post_repository
from app.schemas.comment import CommentCreate, CommentUpdate


def get_comment_or_404(db: Session, comment_id: int) -> Comment:
    comment = comment_repository.get_comment_with_author(db, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


def ensure_post_exists(db: Session, post_id: int) -> None:
    if not post_repository.post_exists(db, post_id):
        raise HTTPException(status_code=404, detail="Post not found")


def list_comments(
    db: Session, post_id: int, offset: int, limit: int
) -> tuple[list[Comment], int]:
    ensure_post_exists(db, post_id)
    comments = comment_repository.list_comments_by_post(db, post_id, offset, limit)
    total = comment_repository.count_comments_by_post(db, post_id)
    return comments, total


def create_comment(
    db: Session, post_id: int, payload: CommentCreate, current_user: User
) -> Comment:
    ensure_post_exists(db, post_id)
    comment = Comment(
        post_id=post_id,
        author_id=current_user.id,
        content=payload.content,
    )
    comment_repository.add_comment(db, comment)
    db.commit()
    db.refresh(comment)
    return get_comment_or_404(db, comment.id)


def update_comment(
    db: Session, comment_id: int, payload: CommentUpdate, current_user: User
) -> Comment:
    comment = get_comment_or_404(db, comment_id)
    if comment.author_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the author can update this comment"
        )

    comment.content = payload.content
    db.commit()
    return get_comment_or_404(db, comment.id)


def delete_comment(db: Session, comment_id: int, current_user: User) -> None:
    comment = get_comment_or_404(db, comment_id)
    if comment.author_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the author can delete this comment"
        )

    comment_repository.delete_comment(db, comment)
    db.commit()
