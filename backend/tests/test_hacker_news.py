from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import news as news_api
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import app
from app.models.post import Post
from app.mcp import board as board_mcp
from app.services import duplicate_check as duplicate_check_module
from app.services.duplicate_check import DuplicateCheckService
from app.services.hacker_news import (
    HackerNewsCandidate,
    HackerNewsService,
    HackerNewsSummary,
)
from app.services.news_curation import NewsCurationService
from test_auth_posts_comments import register_and_login


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
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

    monkeypatch.setattr(news_api, "sync_post_index", lambda db, post: None)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class FakeHackerNewsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []

    def preview(
        self,
        db: Session,
        source: str,
        query: str | None,
        limit: int,
    ) -> list[HackerNewsCandidate]:
        self.calls.append((source, query, limit))
        if source == "search":
            return [
                HackerNewsCandidate(
                    hn_id=200,
                    title=f"{query} story",
                    url="https://example.com/search",
                    hn_url="https://news.ycombinator.com/item?id=200",
                    author="searcher",
                    points=5,
                    comment_count=2,
                    created_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
                    summary_status="success",
                    summary="검색 결과 요약",
                    key_points=["검색 포인트"],
                    is_imported=False,
                    error=None,
                )
            ]
        return [
            HackerNewsCandidate(
                hn_id=100,
                title="Top story",
                url="https://example.com/top",
                hn_url="https://news.ycombinator.com/item?id=100",
                author="alice",
                points=10,
                comment_count=3,
                created_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
                summary_status="success",
                summary="상위 기사 요약",
                key_points=["핵심 1", "핵심 2"],
                is_imported=False,
                error=None,
            )
        ]


class FailedHackerNewsService:
    def preview(
        self,
        db: Session,
        source: str,
        query: str | None,
        limit: int,
    ) -> list[HackerNewsCandidate]:
        return [
            HackerNewsCandidate(
                hn_id=300,
                title="No OpenAI",
                url="https://example.com/fail",
                hn_url="https://news.ycombinator.com/item?id=300",
                author=None,
                points=None,
                comment_count=None,
                created_at=None,
                summary_status="failed",
                summary=None,
                key_points=[],
                is_imported=False,
                error="OPENAI_API_KEY is required",
            )
        ]


def test_hacker_news_preview_requires_login(client: TestClient) -> None:
    response = client.post(
        "/api/news/hacker-news/preview",
        json={"source": "top", "limit": 1},
    )
    assert response.status_code == 401


def test_hacker_news_preview_top_and_search(
    client: TestClient,
) -> None:
    service = FakeHackerNewsService()
    app.dependency_overrides[news_api.get_hacker_news_service_dependency] = lambda: service
    register_and_login(client)

    top_response = client.post(
        "/api/news/hacker-news/preview",
        json={"source": "top", "limit": 1},
    )
    assert top_response.status_code == 200
    top_payload = top_response.json()
    assert top_payload["items"][0]["hn_id"] == 100
    assert top_payload["items"][0]["summary_status"] == "success"
    assert top_payload["items"][0]["duplicate_matches"] == []

    search_response = client.post(
        "/api/news/hacker-news/preview",
        json={"source": "search", "query": "fastapi", "limit": 1},
    )
    assert search_response.status_code == 200
    assert search_response.json()["items"][0]["title"] == "fastapi story"
    assert service.calls == [("top", None, 1), ("search", "fastapi", 1)]


def test_hacker_news_service_fetches_firebase_and_algolia_without_network(
    client: TestClient,
) -> None:
    class LocalHackerNewsService(HackerNewsService):
        search_urls: list[str] = []

        def _get_json(self, url: str, params: dict[str, object] | None = None) -> object:
            if url.endswith("topstories.json"):
                return [101]
            if url.endswith("beststories.json"):
                return [102]
            if url.endswith("newstories.json"):
                return [103]
            if "item/" in url:
                item_id = int(url.rsplit("/", 1)[-1].split(".")[0])
                return {
                    "id": item_id,
                    "type": "story",
                    "title": f"Story {item_id}",
                    "url": f"https://example.com/{item_id}",
                    "by": "author",
                    "score": 7,
                    "descendants": 1,
                    "time": 1781568000,
                }
            self.search_urls.append(url)
            return {
                "hits": [
                    {
                        "objectID": "201",
                        "title": "Search story",
                        "url": "https://example.com/search",
                        "author": "searcher",
                        "points": 9,
                        "num_comments": 4,
                        "created_at": "2026-06-16T00:00:00Z",
                    }
                ]
            }

        def extract_article_text(self, url: str) -> str:
            return "본문 " * 100

        def summarize_article(self, title: str, url: str, article_text: str) -> HackerNewsSummary:
            return HackerNewsSummary(summary=f"{title} 요약", key_points=["핵심"])

    register_and_login(client)
    service = LocalHackerNewsService()
    app.dependency_overrides[news_api.get_hacker_news_service_dependency] = lambda: service

    for source, hn_id in [("top", 101), ("best", 102), ("new", 103)]:
        response = client.post(
            "/api/news/hacker-news/preview",
            json={"source": source, "limit": 1},
        )
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["hn_id"] == hn_id
        assert item["summary_status"] == "success"

    search_response = client.post(
        "/api/news/hacker-news/preview",
        json={"source": "search", "query": "postgres", "limit": 1},
    )
    assert search_response.status_code == 200
    assert search_response.json()["items"][0]["hn_id"] == 201
    assert service.search_urls == ["https://hn.algolia.com/api/v1/search"]


def test_hacker_news_preview_returns_failed_item_when_summary_unavailable(
    client: TestClient,
) -> None:
    app.dependency_overrides[news_api.get_hacker_news_service_dependency] = (
        lambda: FailedHackerNewsService()
    )
    register_and_login(client)
    response = client.post(
        "/api/news/hacker-news/preview",
        json={"source": "best", "limit": 1},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["summary_status"] == "failed"
    assert item["error"] == "OPENAI_API_KEY is required"


def test_hacker_news_llm_debug_logs_model_request_and_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeResponse:
        content = '{"summary": "요약", "key_points": ["핵심"]}'

    class FakeLlm:
        def invoke(self, messages: list[tuple[str, str]]) -> FakeResponse:
            assert "본문" in messages[1][1]
            return FakeResponse()

    service = HackerNewsService(
        Settings(
            openai_api_key="test-key",
            openai_chat_model="gpt-test",
            news_llm_debug=True,
        )
    )
    service._llm = FakeLlm()

    with caplog.at_level("INFO", logger="app.services.hacker_news"):
        summary = service.summarize_article(
            "테스트 제목",
            "https://example.com/article",
            "본문 " * 100,
        )

    assert summary.summary == "요약"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "HN LLM request model=gpt-test" in messages
    assert "HN LLM response model=gpt-test" in messages
    assert "article_chars=" in messages
    assert "response_chars=" in messages


def test_hacker_news_import_creates_post_and_skips_duplicates(
    client: TestClient,
) -> None:
    register_and_login(client)
    payload = {
        "items": [
            {
                "hn_id": 123,
                "title": "Original HN title",
                "url": "https://example.com/article",
                "hn_url": "https://news.ycombinator.com/item?id=123",
                "summary": "한국어 요약",
                "key_points": ["핵심 포인트 1", "핵심 포인트 2"],
            }
        ]
    }

    create_response = client.post("/api/news/hacker-news/import", json=payload)
    assert create_response.status_code == 200
    created = create_response.json()["created"][0]
    assert created["hn_id"] == 123

    duplicate_response = client.post("/api/news/hacker-news/import", json=payload)
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["created"] == []
    assert duplicate_response.json()["skipped"] == [
        {"hn_id": 123, "reason": "already_imported"}
    ]

    post_response = client.get(f"/api/posts/{created['post_id']}")
    assert post_response.status_code == 200
    post = post_response.json()
    assert post["source_type"] == "hacker_news"
    assert post["source_id"] == "123"
    assert "## 한국어 요약" in post["content"]
    assert "#hackernews #technews" in post["content"]


def test_hacker_news_import_rejects_blank_summary(client: TestClient) -> None:
    register_and_login(client)
    response = client.post(
        "/api/news/hacker-news/import",
        json={
            "items": [
                {
                    "hn_id": 123,
                    "title": "Original HN title",
                    "url": "https://example.com/article",
                    "hn_url": "https://news.ycombinator.com/item?id=123",
                    "summary": " ",
                    "key_points": ["핵심"],
                }
            ]
        },
    )
    assert response.status_code == 422


def test_hacker_news_import_survives_rag_index_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_and_login(client)

    def fail_index(db: Session, post: Post) -> None:
        raise RuntimeError("index failed")

    monkeypatch.setattr(news_api, "sync_post_index", fail_index)
    response = client.post(
        "/api/news/hacker-news/import",
        json={
            "items": [
                {
                    "hn_id": 124,
                    "title": "RAG failure still imports",
                    "url": "https://example.com/article",
                    "hn_url": "https://news.ycombinator.com/item?id=124",
                    "summary": "한국어 요약",
                    "key_points": ["핵심"],
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["created"][0]["hn_id"] == 124


def test_web_article_preview_requires_login(client: TestClient) -> None:
    response = client.post(
        "/api/news/web/preview",
        json={"url": "https://example.com/article", "article_text": "본문 " * 100},
    )
    assert response.status_code == 401


def test_web_article_preview_imports_and_skips_duplicate(client: TestClient) -> None:
    class FakeResponse:
        content = '{"summary": "웹 기사 요약", "key_points": ["핵심 1", "핵심 2"]}'

    class FakeLlm:
        def invoke(self, messages: list[tuple[str, str]]) -> FakeResponse:
            assert "본문" in messages[1][1]
            return FakeResponse()

    service = NewsCurationService(Settings(openai_api_key="test-key"))
    service._llm = FakeLlm()
    app.dependency_overrides[news_api.get_news_curation_service_dependency] = lambda: service
    register_and_login(client)

    preview_response = client.post(
        "/api/news/web/preview",
        json={"url": "https://example.com/articles/fastapi-news", "article_text": "본문 " * 100},
    )
    assert preview_response.status_code == 200
    item = preview_response.json()["item"]
    assert item["source_type"] == "web_article"
    assert item["summary_status"] == "success"
    assert item["summary"] == "웹 기사 요약"
    assert item["duplicate_matches"] == []

    import_response = client.post("/api/news/web/import", json={"items": [item]})
    assert import_response.status_code == 200
    created = import_response.json()["created"][0]
    assert created["source_id"] == item["source_id"]

    duplicate_response = client.post("/api/news/web/import", json={"items": [item]})
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["created"] == []
    assert duplicate_response.json()["skipped"] == [
        {"source_id": item["source_id"], "reason": "already_imported"}
    ]

    post_response = client.get(f"/api/posts/{created['post_id']}")
    assert post_response.status_code == 200
    post = post_response.json()
    assert post["source_type"] == "web_article"
    assert post["source_url"] == "https://example.com/articles/fastapi-news"
    assert "#technews #webarticle" in post["content"]


def test_web_article_preview_returns_failed_item_without_openai(client: TestClient) -> None:
    service = NewsCurationService(Settings(openai_api_key=None))
    app.dependency_overrides[news_api.get_news_curation_service_dependency] = lambda: service
    register_and_login(client)

    response = client.post(
        "/api/news/web/preview",
        json={"url": "https://example.com/no-key", "article_text": "본문 " * 100},
    )
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["summary_status"] == "failed"
    assert item["error"] == "OPENAI_API_KEY is required"


def test_duplicate_check_service_url_title_rag_and_rag_failure_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    class FakeDocument:
        metadata = {"post_id": 3, "title": "Vector duplicate"}

    class FakeVectorStore:
        def similarity_search_with_score(self, query: str, k: int) -> list:
            return [(FakeDocument(), 0.2)]

    class FakeRagService:
        def __init__(self, fail: bool = False) -> None:
            self.fail = fail

        def is_configured(self) -> bool:
            return True

        def _get_vector_store(self) -> FakeVectorStore:
            if self.fail:
                raise RuntimeError("vector down")
            return FakeVectorStore()

    with TestingSessionLocal() as db:
        db.add_all(
            [
                Post(
                    title="Exact URL",
                    content="body",
                    author_id=1,
                    source_url="https://Example.com/article/#section",
                ),
                Post(title="FastAPI release notes", content="body", author_id=1),
                Post(title="Vector duplicate", content="body", author_id=1),
            ]
        )
        db.commit()

        monkeypatch.setattr(
            duplicate_check_module,
            "get_rag_service",
            lambda: FakeRagService(),
        )
        matches = DuplicateCheckService().check(
            db,
            title="FastAPI release note",
            url="https://example.com/article",
            content="FastAPI content",
        )
        assert [match.reason for match in matches] == ["same_url", "similar_title", "rag"]
        assert [match.post_id for match in matches] == [1, 2, 3]

        monkeypatch.setattr(
            duplicate_check_module,
            "get_rag_service",
            lambda: FakeRagService(fail=True),
        )
        fallback = DuplicateCheckService().check(
            db,
            title="FastAPI release note",
            url="https://example.com/article",
            content="FastAPI content",
        )
        assert [match.reason for match in fallback] == ["same_url", "similar_title"]


def test_board_mcp_duplicate_tool_is_preview_only(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        db.add(
            Post(
                title="MCP article",
                content="body",
                author_id=1,
                source_url="https://example.com/mcp",
            )
        )
        db.commit()

    monkeypatch.setattr(board_mcp, "get_session_local", lambda: TestingSessionLocal)
    matches = board_mcp.check_news_duplicates_tool(
        title="MCP article",
        url="https://example.com/mcp",
    )
    assert matches == [
        {"post_id": 1, "title": "MCP article", "reason": "same_url", "score": None}
    ]
