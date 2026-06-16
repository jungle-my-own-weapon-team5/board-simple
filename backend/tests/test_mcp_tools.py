from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base
from app.mcp import tools as mcp_tools
from app.models.comment import Comment
from app.models.post import Post
from app.models.user import User


@pytest.fixture()
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(mcp_tools, "get_session_local", lambda: TestingSessionLocal)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        get_settings.cache_clear()


def create_user(db: Session, email: str = "mcp@example.com") -> User:
    user = User(email=email, password_hash="unused", nickname="mcp-user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_seed_post(db: Session, author: User) -> Post:
    post = Post(title="Hello MCP", content="Markdown body #Python", author_id=author.id)
    comment = Comment(post=post, author_id=author.id, content="first comment")
    db.add_all([post, comment])
    db.commit()
    db.refresh(post)
    return post


def test_mcp_tools_read_posts_comments_and_tags(db_session: Session) -> None:
    author = create_user(db_session)
    post = create_seed_post(db_session, author)

    search_result = mcp_tools.search_posts(q="MCP")
    assert search_result.total == 1
    assert search_result.items[0].title == "Hello MCP"

    post_result = mcp_tools.get_post(post.id)
    assert post_result.content == "Markdown body #Python"

    comments = mcp_tools.get_comments(post.id)
    assert comments.total == 1
    assert comments.items[0].content == "first comment"

    thread = mcp_tools.get_post_with_comments(post.id)
    assert thread.post.id == post.id
    assert thread.comments.total == 1


def test_create_post_uses_configured_mcp_author(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_user(db_session)
    monkeypatch.setenv("MCP_AUTHOR_EMAIL", "mcp@example.com")
    get_settings.cache_clear()

    post = mcp_tools.create_post(title="Created by MCP", content="Body #FastAPI")

    assert post.title == "Created by MCP"
    assert post.author.email == "mcp@example.com"
    assert [tag.name for tag in post.tags] == ["fastapi"]


def test_create_post_rejects_missing_author(db_session: Session) -> None:
    with pytest.raises(ValueError, match="author user not found"):
        mcp_tools.create_post(
            title="Created by MCP",
            content="Body",
            author_email="missing@example.com",
        )


def test_create_post_rejects_empty_title(db_session: Session) -> None:
    create_user(db_session)
    with pytest.raises(ValueError, match="title must not be empty"):
        mcp_tools.create_post(
            title=" ",
            content="Body",
            author_email="mcp@example.com",
        )


def test_create_post_rejects_empty_content(db_session: Session) -> None:
    create_user(db_session)
    with pytest.raises(ValueError, match="content must not be empty"):
        mcp_tools.create_post(
            title="Created by MCP",
            content=" ",
            author_email="mcp@example.com",
        )


def test_get_post_rejects_missing_post(db_session: Session) -> None:
    with pytest.raises(ValueError, match="post not found"):
        mcp_tools.get_post(999)


def test_mcp_app_is_mounted() -> None:
    from app.main import create_app

    app = create_app()
    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)

    with TestClient(app, base_url="http://localhost:8000") as client:
        response = client.get("/mcp")

    assert response.status_code == 406
    assert "text/event-stream" in response.text
