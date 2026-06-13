from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.post import Post
from app.models.user import User
from app.repositories import posts as post_repository
from app.schemas.post import PostCreate, PostUpdate
from app.services.tags import extract_tag_names, get_or_create_tags


def get_post_or_404(db: Session, post_id: int) -> Post:
    post = post_repository.get_post_with_author_and_tags(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


def list_posts(db: Session, page: int, size: int, q: str | None = None) -> tuple[list[Post], int]:
    posts = post_repository.list_posts(db, page=page, size=size, q=q)
    total = post_repository.count_posts(db, q=q)
    return posts, total


def create_post(db: Session, payload: PostCreate, current_user: User) -> Post:
    post = Post(title=payload.title, content=payload.content, author_id=current_user.id)
    post.tags = get_or_create_tags(db, extract_tag_names(payload.content))
    post_repository.add_post(db, post)
    db.commit()
    db.refresh(post)
    return get_post_or_404(db, post.id)


def update_post(
    db: Session, post_id: int, payload: PostUpdate, current_user: User
) -> Post:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can update this post")

    post.title = payload.title
    post.content = payload.content
    post.tags = get_or_create_tags(db, extract_tag_names(payload.content))
    db.commit()
    return get_post_or_404(db, post.id)


def delete_post(db: Session, post_id: int, current_user: User) -> None:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this post")

    post_repository.delete_post(db, post)
    db.commit()
