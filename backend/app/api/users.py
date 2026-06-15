from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.comment import Comment
from app.models.post import Post
from app.models.user import User
from app.schemas.post import PostListItem, PostPage
from app.schemas.user import MyCommentPage, MyCommentRead, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserRead)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    nickname = payload.nickname.strip()
    if len(nickname) < 2:
        raise HTTPException(status_code=422, detail="Nickname must be at least 2 characters")

    nickname_owner = db.scalar(select(User).where(User.nickname == nickname))
    if nickname_owner is not None and nickname_owner.id != current_user.id:
        raise HTTPException(status_code=409, detail="Nickname already registered")

    current_user.nickname = nickname
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/me/posts", response_model=PostPage)
def list_my_posts(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostPage:
    total = db.scalar(
        select(func.count()).select_from(Post).where(Post.author_id == current_user.id)
    ) or 0
    posts = db.scalars(
        select(Post)
        .where(Post.author_id == current_user.id)
        .options(selectinload(Post.author), selectinload(Post.tags))
        .order_by(Post.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return PostPage(
        items=[PostListItem.model_validate(post) for post in posts],
        total=total,
        page=page,
        size=size,
    )


@router.get("/me/comments", response_model=MyCommentPage)
def list_my_comments(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MyCommentPage:
    total = db.scalar(
        select(func.count()).select_from(Comment).where(Comment.author_id == current_user.id)
    ) or 0
    rows = db.execute(
        select(Comment, Post.title)
        .join(Post, Post.id == Comment.post_id)
        .where(Comment.author_id == current_user.id)
        .order_by(Comment.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return MyCommentPage(
        items=[
            MyCommentRead(
                id=comment.id,
                post_id=comment.post_id,
                post_title=post_title,
                content=comment.content,
                created_at=comment.created_at,
                updated_at=comment.updated_at,
            )
            for comment, post_title in rows
        ],
        total=total,
        page=page,
        size=size,
    )
