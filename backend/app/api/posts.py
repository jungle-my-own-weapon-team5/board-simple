from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.post import Post
from app.models.user import User
from app.schemas.post import PostCreate, PostListItem, PostPage, PostRead, PostUpdate
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
    post_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    sort: str = Query(default="latest", pattern="^(latest|comments|ai)$"),
    db: Session = Depends(get_db),
) -> PostPage:
    filters = []
    if q:
        filters.append(Post.title.ilike(f"%{q}%"))
    if post_type:
        filters.append(Post.post_type == post_type)
    if category:
        filters.append(Post.category == category)
    if sort == "ai":
        filters.append(Post.has_ai_evidence.is_(True))

    total_statement = select(func.count()).select_from(Post)
    statement = select(Post).options(selectinload(Post.author), selectinload(Post.tags))
    if filters:
        total_statement = total_statement.where(*filters)
        statement = statement.where(*filters)

    total = db.scalar(total_statement) or 0
    if sort == "comments":
        statement = statement.order_by(Post.comment_count.desc(), Post.created_at.desc())
    elif sort == "ai":
        statement = statement.order_by(Post.created_at.desc())
    else:
        statement = statement.order_by(Post.created_at.desc())

    posts = db.scalars(statement.offset((page - 1) * size).limit(size)).all()
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
    post = Post(
        title=payload.title,
        content=payload.content,
        post_type=payload.post_type,
        category=payload.category,
        author_id=current_user.id,
    )
    post.tags = get_or_create_tags(db, extract_tag_names(payload.content))
    db.add(post)
    db.commit()
    db.refresh(post)
    return get_post_or_404(db, post.id)


@router.get("/{post_id}", response_model=PostRead)
def read_post(post_id: int, db: Session = Depends(get_db)) -> Post:
    return get_post_or_404(db, post_id)


@router.post("/{post_id}/view", response_model=PostRead)
def increment_post_view(post_id: int, db: Session = Depends(get_db)) -> Post:
    post = get_post_or_404(db, post_id)
    post.view_count += 1
    db.commit()
    return get_post_or_404(db, post_id)


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
    post.post_type = payload.post_type
    post.category = payload.category
    post.tags = get_or_create_tags(db, extract_tag_names(payload.content))
    db.commit()
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

    db.delete(post)
    db.commit()
