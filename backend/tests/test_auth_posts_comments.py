from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

FRONTEND_ORIGIN = "http://localhost:3000"


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


def origin_headers(origin: str = FRONTEND_ORIGIN) -> dict[str, str]:
    return {"Origin": origin}


def register_and_login(client: TestClient, email: str = "user@example.com") -> dict:
    user_payload = {
        "email": email,
        "password": "password123",
        "nickname": "tester" if email == "user@example.com" else None,
    }
    register_response = client.post(
        "/api/auth/register", json=user_payload, headers=origin_headers()
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
        headers=origin_headers(),
    )
    assert login_response.status_code == 200
    return login_response.json()


def assert_public_author(author: dict) -> None:
    assert "id" in author
    assert "nickname" in author
    assert "email" not in author


def test_register_login_me_and_logout(client: TestClient) -> None:
    user = register_and_login(client)
    assert user["email"] == "user@example.com"
    assert user["nickname"] == "tester"

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "user@example.com"

    logout_response = client.post("/api/auth/logout", headers=origin_headers())
    assert logout_response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_state_changing_requests_require_allowed_origin(client: TestClient) -> None:
    payload = {
        "email": "origin@example.com",
        "password": "password123",
        "nickname": "origin",
    }

    missing_origin_response = client.post("/api/auth/register", json=payload)
    assert missing_origin_response.status_code == 403

    wrong_origin_response = client.post(
        "/api/auth/register",
        json=payload,
        headers=origin_headers("https://evil.example"),
    )
    assert wrong_origin_response.status_code == 403

    assert client.get("/api/posts").status_code == 200


def test_register_rejects_duplicate_email_and_nickname(client: TestClient) -> None:
    register_and_login(client)

    duplicate_email_response = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "password123",
            "nickname": "other-name",
        },
        headers=origin_headers(),
    )
    assert duplicate_email_response.status_code == 409
    assert duplicate_email_response.json()["detail"] == "Email already registered"

    duplicate_nickname_response = client.post(
        "/api/auth/register",
        json={
            "email": "unique@example.com",
            "password": "password123",
            "nickname": "tester",
        },
        headers=origin_headers(),
    )
    assert duplicate_nickname_response.status_code == 409
    assert duplicate_nickname_response.json()["detail"] == "Nickname already registered"


def test_post_crud_search_tags_and_permissions(client: TestClient) -> None:
    register_and_login(client)
    create_response = client.post(
        "/api/posts",
        json={"title": "Hello board", "content": "Markdown body #Python #python #FastAPI"},
        headers=origin_headers(),
    )
    assert create_response.status_code == 201
    post = create_response.json()
    assert [tag["name"] for tag in post["tags"]] == ["python", "fastapi"]
    assert_public_author(post["author"])

    list_response = client.get("/api/posts", params={"q": "board", "page": 1, "size": 10})
    assert list_response.status_code == 200
    post_page = list_response.json()
    assert post_page["total"] == 1
    assert_public_author(post_page["items"][0]["author"])

    detail_response = client.get(f"/api/posts/{post['id']}")
    assert detail_response.status_code == 200
    assert_public_author(detail_response.json()["author"])

    other_user = register_and_login(client, "other@example.com")
    assert other_user["nickname"].startswith("익명")
    forbidden_response = client.put(
        f"/api/posts/{post['id']}",
        json={"title": "Bad edit", "content": "Nope"},
        headers=origin_headers(),
    )
    assert forbidden_response.status_code == 403

    client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "password123"},
        headers=origin_headers(),
    )
    update_response = client.put(
        f"/api/posts/{post['id']}",
        json={"title": "Updated board", "content": "Updated #Django"},
        headers=origin_headers(),
    )
    assert update_response.status_code == 200
    assert update_response.json()["tags"][0]["name"] == "django"

    second_post_response = client.post(
        "/api/posts",
        json={"title": "Reuse tags", "content": "Another body #Python #FastAPI"},
        headers=origin_headers(),
    )
    assert second_post_response.status_code == 201
    assert [tag["name"] for tag in second_post_response.json()["tags"]] == [
        "python",
        "fastapi",
    ]


def test_comment_pagination(client: TestClient) -> None:
    register_and_login(client)
    post_response = client.post(
        "/api/posts",
        json={"title": "Comment target", "content": "Body"},
        headers=origin_headers(),
    )
    post_id = post_response.json()["id"]

    for index in range(7):
        response = client.post(
            f"/api/posts/{post_id}/comments",
            json={"content": f"comment {index}"},
            headers=origin_headers(),
        )
        assert response.status_code == 201

    first_page = client.get(f"/api/posts/{post_id}/comments")
    assert first_page.status_code == 200
    first_page_payload = first_page.json()
    assert len(first_page_payload["items"]) == 5
    assert first_page_payload["total"] == 7
    assert_public_author(first_page_payload["items"][0]["author"])

    next_page = client.get(
        f"/api/posts/{post_id}/comments",
        params={"offset": 5, "limit": 5},
    )
    assert next_page.status_code == 200
    assert len(next_page.json()["items"]) == 2
