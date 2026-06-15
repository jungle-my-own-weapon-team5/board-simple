from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.post import Post
from app.models.tag import Tag


def _post_with_relations():
    return select(Post).options(selectinload(Post.author), selectinload(Post.tags))


def _title_filter(q: str | None):
    return Post.title.ilike(f"%{q}%") if q else None


def get_post(db: Session, post_id: int) -> Post | None:
    return db.scalar(_post_with_relations().where(Post.id == post_id))


def post_exists(db: Session, post_id: int) -> bool:
    return db.scalar(select(Post.id).where(Post.id == post_id)) is not None


def count_posts(db: Session, q: str | None = None) -> int:
    statement = select(func.count()).select_from(Post)
    title_filter = _title_filter(q)
    if title_filter is not None:
        statement = statement.where(title_filter)
    return db.scalar(statement) or 0


def list_posts(db: Session, *, page: int, size: int, q: str | None = None) -> list[Post]:
    statement = _post_with_relations()
    title_filter = _title_filter(q)
    if title_filter is not None:
        statement = statement.where(title_filter)

    return list(
        db.scalars(
            statement.order_by(Post.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
    )


def create_post(
    db: Session,
    *,
    title: str,
    content: str,
    author_id: int,
    tags: list[Tag],
) -> Post:
    post = Post(title=title, content=content, author_id=author_id)
    post.tags = tags
    db.add(post)
    db.flush()
    return post


def update_post(post: Post, *, title: str, content: str, tags: list[Tag]) -> Post:
    post.title = title
    post.content = content
    post.tags = tags
    return post


def delete_post(db: Session, post: Post) -> None:
    db.delete(post)
    db.flush()


def list_posts_for_rag_backfill(
    db: Session,
    *,
    post_ids: list[int] | None = None,
) -> list[Post]:
    statement = select(Post).options(selectinload(Post.tags))
    if post_ids is not None:
        statement = statement.where(Post.id.in_(post_ids))
    return list(db.scalars(statement.order_by(Post.id)).all())
