from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.main import app


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

    def override_get_settings() -> Settings:
        return Settings(openai_api_key=None)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register_and_login(client: TestClient, email: str = "user@example.com") -> dict:
    user_payload = {
        "email": email,
        "password": "password123",
        "nickname": "tester" if email == "user@example.com" else None,
    }
    register_response = client.post("/api/auth/register", json=user_payload)
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200
    return login_response.json()


def test_register_login_me_and_logout(client: TestClient) -> None:
    user = register_and_login(client)
    assert user["email"] == "user@example.com"
    assert user["nickname"] == "tester"
    assert user["is_admin"] is False

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "user@example.com"
    assert me_response.json()["is_admin"] is False

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_post_crud_search_tags_and_permissions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_generate_thumbnail_image",
        lambda settings, prompt: ("/static/generated/test-thumbnail.png", "ok"),
    )

    register_and_login(client)
    create_response = client.post(
        "/api/posts",
        json={"title": "Hello board", "content": "Markdown body #Python #python #FastAPI"},
    )
    assert create_response.status_code == 201
    post = create_response.json()
    assert [tag["name"] for tag in post["tags"]] == ["python", "fastapi"]
    assert post["post_type"] == "토론"
    assert post["category"] == "왕과 권력"
    assert "Hello board" in post["ai_search_summary"]
    assert post["has_ai_evidence"] is True
    assert post["thumbnail_url"] == "/static/generated/test-thumbnail.png"

    list_response = client.get("/api/posts", params={"q": "board", "page": 1, "size": 10})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    other_user = register_and_login(client, "other@example.com")
    assert other_user["nickname"].startswith("익명")
    forbidden_response = client.put(
        f"/api/posts/{post['id']}",
        json={"title": "Bad edit", "content": "Nope"},
    )
    assert forbidden_response.status_code == 403

    client.post("/api/auth/login", json={"email": "user@example.com", "password": "password123"})
    update_response = client.put(
        f"/api/posts/{post['id']}",
        json={"title": "Updated board", "content": "Updated #Django"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["tags"][0]["name"] == "django"
    assert "Updated board" in update_response.json()["ai_search_summary"]

    thumbnail_response = client.post(f"/api/posts/{post['id']}/thumbnail")
    assert thumbnail_response.status_code == 200
    assert thumbnail_response.json()["thumbnail_url"].startswith("/static/generated/")


def test_post_discussion_fields_filters_and_ai_endpoints(client: TestClient) -> None:
    register_and_login(client)
    create_response = client.post(
        "/api/posts",
        json={
            "title": "세조와 단종 토론",
            "content": "계유정난을 어떻게 볼까요? #세조 #단종",
            "post_type": "질문",
            "category": "왕과 권력",
        },
    )
    assert create_response.status_code == 201
    post = create_response.json()
    assert post["post_type"] == "질문"

    list_response = client.get("/api/posts", params={"post_type": "질문"})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    topics_response = client.get("/api/ai/topics")
    assert topics_response.status_code == 200
    assert len(topics_response.json()) == 3

    assist_response = client.post(
        "/api/ai/writing-assist",
        json={"title": post["title"], "content": post["content"], "post_type": "질문"},
    )
    assert assist_response.status_code == 200
    assert "세조" in assist_response.json()["tags"]

    rag_response = client.post("/api/ai/rag/search", json={"query": post["title"], "top_k": 2})
    assert rag_response.status_code == 200
    assert "citations" in rag_response.json()

    rag_agent_response = client.post(
        "/api/ai/rag/agent-search",
        json={"query": post["title"], "top_k": 2},
    )
    assert rag_agent_response.status_code == 200
    rag_agent_payload = rag_agent_response.json()
    assert rag_agent_payload["attempts"]
    assert rag_agent_payload["agent_steps"][0]["name"] == "intent"
    assert "final_query" in rag_agent_payload

    chat_response = client.post(
        "/api/ai/agent/chat",
        json={"message": "세조와 단종 토론 근거를 알려줘", "page_context": {"path": "/"}},
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["steps"][0]["name"] == "langgraph.chat"
    assert chat_payload["final_answer"]

    food_rag_response = client.post(
        "/api/ai/rag/search",
        json={"query": "세종의 식성", "top_k": 3},
    )
    assert food_rag_response.status_code == 200
    food_payload = food_rag_response.json()
    assert food_payload["citations"][0]["title"] == "세종의 식생활과 건강"


def test_mcp_json_rpc_initialize_list_and_call(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    initialize_response = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert initialize_response.status_code == 200
    initialize_payload = initialize_response.json()
    assert initialize_payload["result"]["serverInfo"]["name"] == "history-board-mcp"

    tools_response = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert tools_response.status_code == 200
    assert tools_response.json()["result"]["tools"][0]["name"] == "history.search_sillok"

    from app.services import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_search_sillok",
        lambda keyword: [
            {
                "title": f"{keyword} 결과",
                "provider": "국사편찬위원회 조선왕조실록",
                "url": "https://sillok.history.go.kr/id/kda_10101001_001",
                "description": "테스트 결과",
            }
        ],
    )
    monkeypatch.setattr(
        mcp_server,
        "_generate_thumbnail_image",
        lambda settings, prompt: (None, "failed"),
    )
    call_response = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "history.search_sillok",
                "arguments": {"keyword": "세종"},
            },
        },
    )
    assert call_response.status_code == 200
    call_payload = call_response.json()
    assert call_payload["result"]["structuredContent"]["resources"][0]["title"] == "세종 결과"
    assert call_payload["result"]["structuredContent"]["tool_log"]["tool"] == "history.search_sillok"

    image_response = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "image.generate_thumbnail",
                "arguments": {
                    "title": "훈민정음 토론",
                    "content": "훈민정음 창제를 정치적 맥락에서 봅니다.",
                    "category": "생활사와 문화",
                    "tags": ["훈민정음", "세종"],
                },
            },
        },
    )
    assert image_response.status_code == 200
    image_payload = image_response.json()
    assert image_payload["result"]["structuredContent"]["image_url"] is None
    assert image_payload["result"]["structuredContent"]["visual_brief"]
    assert image_payload["result"]["structuredContent"]["tool_log"]["tool"] == "image.generate_thumbnail"


def test_admin_thumbnail_preview_requires_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_generate_thumbnail_image",
        lambda settings, prompt: ("/static/generated/admin-preview.png", "ok"),
    )

    register_and_login(client)
    forbidden_response = client.post(
        "/api/admin/thumbnail/preview",
        json={
            "title": "양녕대군 고양이 사건",
            "content": "양녕대군이 금빛 고양이를 탐냈다는 왕실 TMI 글입니다.",
            "category": "왕실 TMI",
            "tags": ["양녕대군", "고양이"],
        },
    )
    assert forbidden_response.status_code == 403

    admin_user = register_and_login(client, "admin@example.com")
    assert admin_user["is_admin"] is True
    preview_response = client.post(
        "/api/admin/thumbnail/preview",
        json={
            "title": "양녕대군 고양이 사건",
            "content": "양녕대군이 금빛 고양이를 탐냈다는 왕실 TMI 글입니다.",
            "category": "왕실 TMI",
            "tags": ["양녕대군", "고양이"],
        },
    )
    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["image_url"] == "/static/generated/admin-preview.png"
    assert "1536x1024" in payload["prompt"]
    assert "pseudo-Korean" in payload["prompt"]


def test_comment_pagination(client: TestClient) -> None:
    register_and_login(client)
    post_response = client.post(
        "/api/posts",
        json={"title": "Comment target", "content": "Body"},
    )
    post_id = post_response.json()["id"]

    for index in range(7):
        response = client.post(
            f"/api/posts/{post_id}/comments",
            json={"content": f"comment {index}"},
        )
        assert response.status_code == 201

    first_page = client.get(f"/api/posts/{post_id}/comments")
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 5
    assert first_page.json()["total"] == 7

    post_detail = client.get(f"/api/posts/{post_id}")
    assert post_detail.status_code == 200
    assert post_detail.json()["comment_count"] == 7
    assert post_detail.json()["view_count"] == 0

    view_response = client.post(f"/api/posts/{post_id}/view")
    assert view_response.status_code == 200
    assert view_response.json()["view_count"] == 1

    next_page = client.get(
        f"/api/posts/{post_id}/comments",
        params={"offset": 5, "limit": 5},
    )
    assert next_page.status_code == 200
    assert len(next_page.json()["items"]) == 2


def test_user_profile_update_and_my_activity(client: TestClient) -> None:
    register_and_login(client)
    post_response = client.post(
        "/api/posts",
        json={"title": "My first post", "content": "Body"},
    )
    assert post_response.status_code == 201
    post_id = post_response.json()["id"]

    comment_response = client.post(
        f"/api/posts/{post_id}/comments",
        json={"content": "내 댓글"},
    )
    assert comment_response.status_code == 201

    update_response = client.patch("/api/users/me", json={"nickname": "newnick"})
    assert update_response.status_code == 200
    assert update_response.json()["nickname"] == "newnick"

    my_posts_response = client.get("/api/users/me/posts")
    assert my_posts_response.status_code == 200
    assert my_posts_response.json()["total"] == 1
    assert my_posts_response.json()["items"][0]["title"] == "My first post"

    my_comments_response = client.get("/api/users/me/comments")
    assert my_comments_response.status_code == 200
    assert my_comments_response.json()["total"] == 1
    assert my_comments_response.json()["items"][0]["post_title"] == "My first post"

    register_and_login(client, "other@example.com")
    duplicate_response = client.patch("/api/users/me", json={"nickname": "newnick"})
    assert duplicate_response.status_code == 409


def test_user_profile_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/users/me/posts").status_code == 401
    assert client.get("/api/users/me/comments").status_code == 401
    assert client.patch("/api/users/me", json={"nickname": "newnick"}).status_code == 401
    assert client.post("/api/ai/agent/chat", json={"message": "세종"}).status_code == 401
