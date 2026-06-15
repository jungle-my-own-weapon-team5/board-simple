from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.rag import get_rag_service_dependency
from app.api import posts as posts_api
from app.core.database import Base, get_db
from app.main import app
from app.models.post import Post
from app.models.rag import PostRagChunk
from app.models.user import User
from app.services.rag import RagAnswerResult, RagService, RagSourceResult, RagUnavailableError


@pytest.fixture()
def rag_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []

    def fake_sync_post_index(db: Session, post: Post) -> None:
        calls.append(("sync", post.id))

    def fake_delete_post_index_safe(db: Session, post_id: int) -> None:
        calls.append(("delete", post_id))

    monkeypatch.setattr(posts_api, "sync_post_index", fake_sync_post_index)
    monkeypatch.setattr(posts_api, "delete_post_index_safe", fake_delete_post_index_safe)
    return calls


@pytest.fixture()
def client(rag_calls: list[tuple[str, int]]) -> Generator[TestClient, None, None]:
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


def test_post_crud_search_tags_permissions_and_rag_hooks(
    client: TestClient,
    rag_calls: list[tuple[str, int]],
) -> None:
    register_and_login(client)
    create_response = client.post(
        "/api/posts",
        json={"title": "Hello board", "content": "Markdown body #Python #python #FastAPI"},
    )
    assert create_response.status_code == 201
    post = create_response.json()
    assert [tag["name"] for tag in post["tags"]] == ["python", "fastapi"]

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

    delete_response = client.delete(f"/api/posts/{post['id']}")
    assert delete_response.status_code == 204
    assert rag_calls == [("sync", post["id"]), ("sync", post["id"]), ("delete", post["id"])]


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

    next_page = client.get(
        f"/api/posts/{post_id}/comments",
        params={"offset": 5, "limit": 5},
    )
    assert next_page.status_code == 200
    assert len(next_page.json()["items"]) == 2


def test_rag_ask_returns_answer_and_sources(client: TestClient) -> None:
    class FakeRagService:
        def ask(self, db: Session, question: str) -> RagAnswerResult:
            assert question == "AI 반도체 이슈는?"
            return RagAnswerResult(
                answer="AI 반도체 수요가 증가하고 있습니다.",
                sources=[
                    RagSourceResult(
                        post_id=1,
                        title="AI chip news",
                        excerpt="Title: AI chip news",
                        score=0.12,
                    )
                ],
            )

    app.dependency_overrides[get_rag_service_dependency] = lambda: FakeRagService()
    response = client.post("/api/rag/ask", json={"question": " AI 반도체 이슈는? "})
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "AI 반도체 수요가 증가하고 있습니다."
    assert payload["sources"][0]["post_id"] == 1
    assert payload["sources"][0]["score"] == 0.12


def test_rag_ask_rejects_blank_question(client: TestClient) -> None:
    response = client.post("/api/rag/ask", json={"question": "   "})
    assert response.status_code == 422


def test_rag_ask_returns_503_when_unavailable(client: TestClient) -> None:
    class UnavailableRagService:
        def ask(self, db: Session, question: str) -> RagAnswerResult:
            raise RagUnavailableError("RAG is disabled")

    app.dependency_overrides[get_rag_service_dependency] = lambda: UnavailableRagService()
    response = client.post("/api/rag/ask", json={"question": "뉴스 요약"})
    assert response.status_code == 503
    assert response.json()["detail"] == "RAG is disabled"


def test_rag_service_updates_chunk_mappings_without_network() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    class FakeVectorStore:
        def __init__(self) -> None:
            self.added_ids: list[list[str]] = []
            self.deleted_ids: list[list[str]] = []

        def add_documents(self, documents: list[object], ids: list[str]) -> None:
            self.added_ids.append(ids)

        def delete(self, ids: list[str]) -> None:
            self.deleted_ids.append(ids)

    class FakeRagService(RagService):
        def __init__(self) -> None:
            self.vector_store = FakeVectorStore()

        def is_configured(self) -> bool:
            return True

        def _get_vector_store(self) -> FakeVectorStore:
            return self.vector_store

        def _documents_for_post(self, post: Post) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(page_content=post.title, metadata={"post_id": post.id}),
                SimpleNamespace(page_content=post.content, metadata={"post_id": post.id}),
            ]

    with TestingSessionLocal() as db:
        user = User(
            email="rag@example.com",
            password_hash="hash",
            nickname="rag",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        post = Post(title="Title", content="Body", author_id=user.id)
        db.add(post)
        db.commit()
        db.refresh(post)

        service = FakeRagService()
        service.index_post(db, post)
        mappings = db.scalars(select(PostRagChunk).where(PostRagChunk.post_id == post.id)).all()
        assert [mapping.document_id for mapping in mappings] == [
            f"post-{post.id}-chunk-0",
            f"post-{post.id}-chunk-1",
        ]

        service.index_post(db, post)
        mappings = db.scalars(select(PostRagChunk).where(PostRagChunk.post_id == post.id)).all()
        assert len(mappings) == 2
        assert service.vector_store.deleted_ids == [
            [f"post-{post.id}-chunk-0", f"post-{post.id}-chunk-1"]
        ]

        service.delete_post_index(db, post.id)
        mappings = db.scalars(select(PostRagChunk).where(PostRagChunk.post_id == post.id)).all()
        assert mappings == []
