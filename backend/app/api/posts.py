from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.post import Post
from app.models.user import User
from app.schemas.post import (
    PostCreate,
    PostListItem,
    PostPage,
    PostRead,
    PostUpdate,
    RelatedPost,
)
from app.services.rag import delete_post_index_safe, get_rag_service, sync_post_index
from app.services.tags import extract_tag_names, get_or_create_tags

router = APIRouter(prefix="/posts", tags=["posts"])


def get_post_or_404(db: Session, post_id: int) -> Post:
    post = db.scalar(
        select(Post)
        .where(Post.id == post_id)
        .options(
            selectinload(Post.author),
            selectinload(Post.tags),
        )
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.get("", response_model=PostPage)
def list_posts(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PostPage:
    filters = []
    if q:
        filters.append(Post.title.ilike(f"%{q}%"))

    total_statement = select(func.count()).select_from(Post)
    statement = select(Post).options(selectinload(Post.author), selectinload(Post.tags))
    if filters:
        total_statement = total_statement.where(*filters)
        statement = statement.where(*filters)

    total = db.scalar(total_statement) or 0
    posts = db.scalars(
        statement.order_by(Post.created_at.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return PostPage(
        items=[PostListItem.model_validate(post) for post in posts],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Post:
    post = Post(title=payload.title, content=payload.content, author_id=current_user.id)
    post.tags = get_or_create_tags(db, extract_tag_names(payload.content))
    db.add(post)
    db.commit()
    db.refresh(post)
    sync_post_index(db, post)
    return get_post_or_404(db, post.id)


@router.get("/{post_id}", response_model=PostRead)
def read_post(post_id: int, db: Session = Depends(get_db)) -> Post:
    return get_post_or_404(db, post_id)


@router.get("/{post_id}/related", response_model=list[RelatedPost])
def read_related_posts(post_id: int, db: Session = Depends(get_db)) -> list[RelatedPost]:
    post = get_post_or_404(db, post_id)
    related_posts = get_rag_service().related_posts(db, post)
    return [
        RelatedPost(
            post_id=related.post_id,
            title=related.title,
            score=related.score,
        )
        for related in related_posts
    ]


@router.put("/{post_id}", response_model=PostRead)
def update_post(
    post_id: int,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Post:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can update this post")

    post.title = payload.title
    post.content = payload.content
    post.tags = get_or_create_tags(db, extract_tag_names(payload.content))
    db.commit()
    sync_post_index(db, post)
    return get_post_or_404(db, post.id)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this post")

    delete_post_index_safe(db, post.id)
    db.delete(post)
    db.commit()
