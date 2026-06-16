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
from app.services.rag import (
    RagAnswerResult,
    RagService,
    RagSourceResult,
    RagUnavailableError,
    RelatedPostResult,
)


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
    assert post["related_posts"] == []

    list_response = client.get("/api/posts", params={"q": "board", "page": 1, "size": 10})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    read_response = client.get(f"/api/posts/{post['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["related_posts"] == []

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


def test_read_post_includes_related_posts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_and_login(client)
    post_response = client.post(
        "/api/posts",
        json={"title": "AI hardware", "content": "GPU and inference"},
    )
    post_id = post_response.json()["id"]
    calls: list[int] = []

    class FakeRagService:
        def related_posts(
            self,
            db: Session,
            post: Post,
            limit: int = 3,
        ) -> list[RelatedPostResult]:
            assert post.id == post_id
            assert limit == 3
            calls.append(post.id)
            return [RelatedPostResult(post_id=42, title="Related title", score=0.25)]

    monkeypatch.setattr(posts_api, "get_rag_service", lambda: FakeRagService())
    detail_response = client.get(f"/api/posts/{post_id}")

    assert detail_response.status_code == 200
    assert detail_response.json()["related_posts"] == []
    assert calls == []

    related_response = client.get(f"/api/posts/{post_id}/related")

    assert related_response.status_code == 200
    assert related_response.json() == [
        {"post_id": 42, "title": "Related title", "score": 0.25}
    ]
    assert calls == [post_id]


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


def test_rag_service_related_posts_filters_vector_results_without_network() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    class FakeVectorStore:
        def __init__(self) -> None:
            self.query: str | None = None
            self.k: int | None = None
            self.results: list[tuple[SimpleNamespace, float | None]] = []

        def similarity_search_with_score(
            self,
            query: str,
            k: int,
        ) -> list[tuple[SimpleNamespace, float | None]]:
            self.query = query
            self.k = k
            return self.results

    class FakeRagService(RagService):
        def __init__(self) -> None:
            self.vector_store = FakeVectorStore()

        def is_configured(self) -> bool:
            return True

        def _get_vector_store(self) -> FakeVectorStore:
            return self.vector_store

    with TestingSessionLocal() as db:
        user = User(email="related@example.com", password_hash="hash", nickname="related")
        db.add(user)
        db.commit()
        db.refresh(user)

        current = Post(title="Current", content="Current body", author_id=user.id)
        first = Post(title="First DB title", content="First body", author_id=user.id)
        second = Post(title="Second DB title", content="Second body", author_id=user.id)
        third = Post(title="Third DB title", content="Third body", author_id=user.id)
        fourth = Post(title="Fourth DB title", content="Fourth body", author_id=user.id)
        db.add_all([current, first, second, third, fourth])
        db.commit()
        for post in [current, first, second, third, fourth]:
            db.refresh(post)

        service = FakeRagService()
        service.vector_store.results = [
            (SimpleNamespace(metadata={"post_id": current.id, "title": "Current"}), 0.01),
            (SimpleNamespace(metadata={"post_id": first.id, "title": "First vector title"}), 0.02),
            (SimpleNamespace(metadata={"post_id": first.id, "title": "Duplicate"}), 0.03),
            (SimpleNamespace(metadata={"post_id": second.id}), 0.04),
            (SimpleNamespace(metadata={}), 0.05),
            (SimpleNamespace(metadata={"post_id": 9999, "title": "Missing"}), 0.06),
            (SimpleNamespace(metadata={"post_id": third.id, "title": "Third vector title"}), None),
            (SimpleNamespace(metadata={"post_id": fourth.id, "title": "Fourth"}), 0.07),
        ]

        related = service.related_posts(db, current, limit=3)

        assert service.vector_store.query == "Title: Current\n\nCurrent body"
        assert service.vector_store.k == 12
        assert related == [
            RelatedPostResult(first.id, "First vector title", 0.02),
            RelatedPostResult(second.id, "Second DB title", 0.04),
            RelatedPostResult(third.id, "Third vector title", None),
        ]


def test_rag_service_related_posts_returns_empty_on_vector_failure() -> None:
    class BrokenVectorStore:
        def similarity_search_with_score(self, query: str, k: int) -> list[object]:
            raise RuntimeError("vector unavailable")

    class FakeRagService(RagService):
        def __init__(self) -> None:
            self.vector_store = BrokenVectorStore()

        def is_configured(self) -> bool:
            return True

        def _get_vector_store(self) -> BrokenVectorStore:
            return self.vector_store

    post = Post(id=1, title="Current", content="Body", author_id=1)
    assert FakeRagService().related_posts(db=object(), post=post) == []
