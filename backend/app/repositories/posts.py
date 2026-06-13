from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.post import Post


def get_post_with_author_and_tags(db: Session, post_id: int) -> Post | None:
    return db.scalar(
        select(Post)
        .where(Post.id == post_id)
        .options(
            selectinload(Post.author),
            selectinload(Post.tags),
        )
    )


def count_posts(db: Session, q: str | None = None) -> int:
    statement = select(func.count()).select_from(Post)
    if q:
        statement = statement.where(Post.title.ilike(f"%{q}%"))
    return db.scalar(statement) or 0


def list_posts(db: Session, page: int, size: int, q: str | None = None) -> list[Post]:
    statement = select(Post).options(selectinload(Post.author), selectinload(Post.tags))
    if q:
        statement = statement.where(Post.title.ilike(f"%{q}%"))
    return list(
        db.scalars(
            statement.order_by(Post.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
    )


def add_post(db: Session, post: Post) -> None:
    db.add(post)


def delete_post(db: Session, post: Post) -> None:
    db.delete(post)
