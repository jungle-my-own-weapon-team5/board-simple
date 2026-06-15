from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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

    app.dependency_overrides[get_db] = override_get_db
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

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "user@example.com"

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_post_crud_search_tags_and_permissions(client: TestClient) -> None:
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
    assert len(rag_response.json()["citations"]) == 2


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
