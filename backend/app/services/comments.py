from sqlalchemy.orm import Session

from app.models.comment import Comment
from app.models.user import User
from app.repositories import comments as comment_repository
from app.repositories import posts as post_repository
from app.schemas.comment import CommentCreate, CommentUpdate
from app.services.errors import NotFoundError, PermissionDeniedError


def _ensure_post_exists(db: Session, post_id: int) -> None:
    if not post_repository.post_exists(db, post_id):
        raise NotFoundError("Post not found")


def _get_comment_or_raise(db: Session, comment_id: int) -> Comment:
    comment = comment_repository.get_comment(db, comment_id)
    if comment is None:
        raise NotFoundError("Comment not found")
    return comment


def list_comments(
    db: Session,
    *,
    post_id: int,
    offset: int,
    limit: int,
) -> tuple[list[Comment], int]:
    _ensure_post_exists(db, post_id)
    return (
        comment_repository.list_comments(
            db,
            post_id=post_id,
            offset=offset,
            limit=limit,
        ),
        comment_repository.count_comments(db, post_id),
    )


def create_comment(
    db: Session,
    *,
    post_id: int,
    payload: CommentCreate,
    current_user: User,
) -> Comment:
    _ensure_post_exists(db, post_id)
    comment = comment_repository.create_comment(
        db,
        post_id=post_id,
        author_id=current_user.id,
        content=payload.content,
    )
    comment_id = comment.id
    db.commit()
    return _get_comment_or_raise(db, comment_id)


def update_comment(
    db: Session,
    *,
    comment_id: int,
    payload: CommentUpdate,
    current_user: User,
) -> Comment:
    comment = _get_comment_or_raise(db, comment_id)
    if comment.author_id != current_user.id:
        raise PermissionDeniedError("Only the author can update this comment")

    comment_repository.update_comment(comment, content=payload.content)
    db.commit()
    return _get_comment_or_raise(db, comment_id)


def delete_comment(db: Session, *, comment_id: int, current_user: User) -> None:
    comment = _get_comment_or_raise(db, comment_id)
    if comment.author_id != current_user.id:
        raise PermissionDeniedError("Only the author can delete this comment")

    comment_repository.delete_comment(db, comment)
    db.commit()
