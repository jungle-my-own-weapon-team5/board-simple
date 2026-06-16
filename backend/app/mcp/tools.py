from collections.abc import Generator
from contextlib import contextmanager
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.database import get_session_local
from app.models.comment import Comment
from app.models.post import Post
from app.models.tag import Tag
from app.models.user import User
from app.mcp.schemas import (
    McpComment,
    McpCommentPage,
    McpPostDetail,
    McpPostListItem,
    McpPostPage,
    McpPostWithComments,
    McpTag,
    McpUser,
)
from app.schemas.post import PostCreate
from app.services import posts as post_service

TAG_PATTERN = re.compile(r"#([0-9A-Za-z가-힣_]{1,50})")


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()


def _validate_page(page: int, size: int) -> None:
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    if size < 1 or size > 50:
        raise ValueError("size must be between 1 and 50")


def _validate_window(offset: int, limit: int) -> None:
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")


def _user_to_mcp(user: User) -> McpUser:
    return McpUser(
        id=user.id,
        email=user.email,
        nickname=user.nickname,
        created_at=user.created_at,
    )


def _tag_to_mcp(tag: Tag) -> McpTag:
    return McpTag(id=tag.id, name=tag.name)


def _post_to_list_item(post: Post) -> McpPostListItem:
    return McpPostListItem(
        id=post.id,
        title=post.title,
        author=_user_to_mcp(post.author),
        tags=[_tag_to_mcp(tag) for tag in post.tags],
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def _post_to_detail(post: Post) -> McpPostDetail:
    return McpPostDetail(
        id=post.id,
        title=post.title,
        content=post.content,
        author=_user_to_mcp(post.author),
        tags=[_tag_to_mcp(tag) for tag in post.tags],
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def _comment_to_mcp(comment: Comment) -> McpComment:
    return McpComment(
        id=comment.id,
        post_id=comment.post_id,
        content=comment.content,
        author=_user_to_mcp(comment.author),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def _get_post_or_error(db: Session, post_id: int) -> Post:
    post = db.scalar(
        select(Post)
        .where(Post.id == post_id)
        .options(selectinload(Post.author), selectinload(Post.tags))
    )
    if post is None:
        raise ValueError(f"post not found: {post_id}")
    return post


def _extract_tag_names(text: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for raw_name in TAG_PATTERN.findall(text):
        name = raw_name.strip().lower()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def search_posts(q: str | None = None, page: int = 1, size: int = 10) -> McpPostPage:
    """Search posts by title and return a paginated result."""
    _validate_page(page, size)
    with session_scope() as db:
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
        return McpPostPage(
            items=[_post_to_list_item(post) for post in posts],
            total=total,
            page=page,
            size=size,
        )


def get_recent_posts(limit: int = 10) -> list[McpPostListItem]:
    """Return the most recent posts."""
    _validate_window(0, limit)
    with session_scope() as db:
        posts = db.scalars(
            select(Post)
            .options(selectinload(Post.author), selectinload(Post.tags))
            .order_by(Post.created_at.desc())
            .limit(limit)
        ).all()
        return [_post_to_list_item(post) for post in posts]


def get_post(post_id: int) -> McpPostDetail:
    """Return one post with author and tags."""
    with session_scope() as db:
        return _post_to_detail(_get_post_or_error(db, post_id))


def get_comments(post_id: int, offset: int = 0, limit: int = 10) -> McpCommentPage:
    """Return comments for a post."""
    _validate_window(offset, limit)
    with session_scope() as db:
        post_exists = db.scalar(select(Post.id).where(Post.id == post_id))
        if post_exists is None:
            raise ValueError(f"post not found: {post_id}")

        total = db.scalar(
            select(func.count()).select_from(Comment).where(Comment.post_id == post_id)
        ) or 0
        comments = db.scalars(
            select(Comment)
            .where(Comment.post_id == post_id)
            .options(selectinload(Comment.author))
            .order_by(Comment.created_at.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return McpCommentPage(
            items=[_comment_to_mcp(comment) for comment in comments],
            total=total,
            offset=offset,
            limit=limit,
        )


def get_post_with_comments(
    post_id: int,
    comment_limit: int = 20,
) -> McpPostWithComments:
    """Return one post and its first comments page for LLM context."""
    _validate_window(0, comment_limit)
    return McpPostWithComments(
        post=get_post(post_id),
        comments=get_comments(post_id, offset=0, limit=comment_limit),
    )


def list_tags() -> list[McpTag]:
    """Return all tags sorted by name."""
    with session_scope() as db:
        tags = db.scalars(select(Tag).order_by(Tag.name.asc())).all()
        return [_tag_to_mcp(tag) for tag in tags]


def create_post(
    title: str,
    content: str,
    author_email: str | None = None,
) -> McpPostDetail:
    """Create a post as the configured MCP author or the provided author email."""
    if not title or not title.strip():
        raise ValueError("title must not be empty")
    if len(title) > 200:
        raise ValueError("title must be 200 characters or fewer")
    if not content or not content.strip():
        raise ValueError("content must not be empty")

    email = author_email or get_settings().mcp_author_email
    if not email:
        raise ValueError("MCP_AUTHOR_EMAIL must be set when author_email is not provided")

    with session_scope() as db:
        author = db.scalar(select(User).where(User.email == email))
        if author is None:
            raise ValueError(f"author user not found: {email}")

        post = post_service.create_post(
            db,
            PostCreate(title=title, content=content, tags=_extract_tag_names(content)),
            author,
        )
        return _post_to_detail(post)
