from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import create_app
from app.mcp.schemas import McpPostDetail, McpPostListItem, McpPostPage, McpTag, McpUser
from app.schemas.agent import AgentChatRequest
from app.services import agent as agent_service


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register_and_login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "email": "agent@example.com",
            "password": "password123",
            "nickname": "agent-user",
        },
    )
    assert response.status_code == 201
    response = client.post(
        "/api/auth/login",
        json={"email": "agent@example.com", "password": "password123"},
    )
    assert response.status_code == 200


def mcp_user() -> McpUser:
    return McpUser(
        id=1,
        email="agent@example.com",
        nickname="agent-user",
        created_at=datetime.now(timezone.utc),
    )


def test_agent_chat_requires_login(client: TestClient) -> None:
    response = client.post("/api/agent/chat", json={"message": "최근 글 보여줘"})

    assert response.status_code == 401


def test_agent_chat_returns_mocked_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_and_login(client)

    def fake_chat_with_agent(payload, current_user):
        assert payload.message == "최근 글 보여줘"
        assert current_user.email == "agent@example.com"
        return {
            "answer": "최근 글 1개가 있습니다.",
            "sources": [
                {
                    "post_id": 1,
                    "title": "Hello",
                    "heading": None,
                    "anchor": None,
                    "snippet": "body",
                }
            ],
            "pending_action": None,
            "created_post": None,
        }

    monkeypatch.setattr("app.api.agent.chat_with_agent", fake_chat_with_agent)

    response = client.post("/api/agent/chat", json={"message": "최근 글 보여줘"})

    assert response.status_code == 200
    assert response.json()["answer"] == "최근 글 1개가 있습니다."
    assert response.json()["sources"][0]["post_id"] == 1


def test_agent_prepares_create_post(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_service,
        "_select_action",
        lambda message: agent_service.AgentActionPlan(
            action="prepare_create_post",
            args={"title": "Agent title", "content": "Agent body #agent"},
        ),
    )

    response = agent_service.chat_with_agent(
        AgentChatRequest(message="이 내용으로 글 써줘"),
        SimpleNamespace(email="agent@example.com"),
    )

    assert response.pending_action is not None
    assert response.pending_action.title == "Agent title"
    assert response.pending_action.content == "Agent body #agent"
    assert response.created_post is None


def test_agent_confirms_create_post(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create_post(title: str, content: str, author_email: str | None = None):
        assert title == "Agent title"
        assert content == "Agent body"
        assert author_email == "agent@example.com"
        return McpPostDetail(
            id=7,
            title=title,
            content=content,
            author=mcp_user(),
            tags=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(agent_service, "create_post", fake_create_post)

    response = agent_service.chat_with_agent(
        AgentChatRequest(
            message="확인",
            confirm_action={
                "type": "create_post",
                "title": "Agent title",
                "content": "Agent body",
            },
        ),
        SimpleNamespace(email="agent@example.com"),
    )

    assert response.created_post is not None
    assert response.created_post.post_id == 7
    assert response.sources[0].post_id == 7


def test_agent_uses_search_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    post_item = McpPostListItem(
        id=3,
        title="FastAPI MCP",
        author=mcp_user(),
        tags=[McpTag(id=1, name="fastapi")],
        created_at=now,
        updated_at=now,
    )

    monkeypatch.setattr(
        agent_service,
        "_select_action",
        lambda message: agent_service.AgentActionPlan(
            action="search_posts",
            args={"q": "FastAPI", "page": 1, "size": 10},
        ),
    )
    monkeypatch.setattr(
        agent_service,
        "search_posts",
        lambda q, page, size: McpPostPage(items=[post_item], total=1, page=page, size=size),
    )
    monkeypatch.setattr(
        agent_service,
        "_answer_with_tool_result",
        lambda message, action, tool_result: "FastAPI MCP 글을 찾았습니다.",
    )

    response = agent_service.chat_with_agent(
        AgentChatRequest(message="FastAPI 찾아줘"),
        SimpleNamespace(email="agent@example.com"),
    )

    assert response.answer == "FastAPI MCP 글을 찾았습니다."
    assert response.sources[0].post_id == 3
