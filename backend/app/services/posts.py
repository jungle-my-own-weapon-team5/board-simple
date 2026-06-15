from sqlalchemy.orm import Session

from app.models.post import Post
from app.models.user import User
from app.repositories import posts as post_repository
from app.schemas.post import PostCreate, PostUpdate
from app.services import rag as rag_service
from app.services.errors import NotFoundError, PermissionDeniedError
from app.services.tags import get_or_create_tags


def _get_post_or_raise(db: Session, post_id: int) -> Post:
    post = post_repository.get_post(db, post_id)
    if post is None:
        raise NotFoundError("Post not found")
    return post


def list_posts(
    db: Session,
    *,
    page: int,
    size: int,
    q: str | None,
) -> tuple[list[Post], int]:
    return (
        post_repository.list_posts(db, page=page, size=size, q=q),
        post_repository.count_posts(db, q=q),
    )


def get_post(db: Session, post_id: int) -> Post:
    return _get_post_or_raise(db, post_id)


def create_post(db: Session, payload: PostCreate, current_user: User) -> Post:
    tags = get_or_create_tags(db, payload.tags)
    post = post_repository.create_post(
        db,
        title=payload.title,
        content=payload.content,
        author_id=current_user.id,
        tags=tags,
    )
    post_id = post.id
    db.commit()

    post = _get_post_or_raise(db, post_id)
    rag_service.index_post_chunks(db, post)
    db.commit()
    return _get_post_or_raise(db, post_id)


def update_post(
    db: Session,
    post_id: int,
    payload: PostUpdate,
    current_user: User,
) -> Post:
    post = _get_post_or_raise(db, post_id)
    if post.author_id != current_user.id:
        raise PermissionDeniedError("Only the author can update this post")

    tags = get_or_create_tags(db, payload.tags)
    post_repository.update_post(
        post,
        title=payload.title,
        content=payload.content,
        tags=tags,
    )
    db.commit()

    post = _get_post_or_raise(db, post_id)
    rag_service.index_post_chunks(db, post)
    db.commit()
    return _get_post_or_raise(db, post_id)


def delete_post(db: Session, post_id: int, current_user: User) -> None:
    post = _get_post_or_raise(db, post_id)
    if post.author_id != current_user.id:
        raise PermissionDeniedError("Only the author can delete this post")

    post_repository.delete_post(db, post)
    db.commit()
