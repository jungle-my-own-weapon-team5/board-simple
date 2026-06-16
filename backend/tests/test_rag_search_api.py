from collections.abc import Generator
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.main import app
from app.models import (
    LegalDocument,
    LegalDocumentChunk,
    LegalSource,
    RagRetrieval,
    RagRun,
)
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding
from app.repositories import (
    document_chunks,
    embeddings as embedding_repository,
    legal_documents,
)
from app.services.rag.legal_source_planner import (
    LegalSourceCandidate,
    LegalSourcePlan,
    PlannedLegalIssue,
)
from app.services.rag.normalization import calculate_text_checksum

FRONTEND_ORIGIN = "http://localhost:3000"


@dataclass(frozen=True)
class ApiTestContext:
    client: TestClient
    session_factory: sessionmaker[Session]


@pytest.fixture()
def rag_client_context() -> Generator[ApiTestContext, None, None]:
    yield from _client_context(_settings(ai_rag_enabled=True))


@pytest.fixture()
def disabled_rag_client_context() -> Generator[ApiTestContext, None, None]:
    yield from _client_context(_settings(ai_rag_enabled=False))


@pytest.fixture()
def law_open_api_rag_client_context() -> Generator[ApiTestContext, None, None]:
    yield from _client_context(
        _settings(ai_rag_enabled=True, law_open_api_oc="test-oc")
    )


def test_rag_search_endpoint_returns_ranked_chunks_and_persists_audit(
    rag_client_context: ApiTestContext,
) -> None:
    register_and_login(rag_client_context.client)
    query = "임대차 보증금 반환"
    query_embedding = _mock_embedding_for_text(query, dimensions=3)
    with rag_client_context.session_factory() as db:
        profile = _create_profile(db, dimensions=3)
        target_embedding = _create_chunk_embedding(
            db,
            profile=profile,
            title="보증금 반환 문서",
            heading="제1조",
            content="임대차 보증금 반환과 지연손해금에 관한 내용",
            embedding=query_embedding,
        )
        _create_chunk_embedding(
            db,
            profile=profile,
            title="무관한 문서",
            heading="제2조",
            content="검색어와 관련성이 낮은 내용",
            embedding=[0.0, 0.0, 0.0],
        )
        target_chunk_id = target_embedding.chunk_id
        profile_id = profile.id
        db.commit()

    response = rag_client_context.client.post(
        "/api/rag/search",
        json={
            "query": query,
            "top_k": 1,
            "filters": {"document_type": "statute"},
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "임대차 보증금 반환"
    assert body["search_mode"] == "focused_answer"
    assert body["top_k"] == 1
    assert body["embedding_profile_id"] == profile_id
    assert body["embedding_provider"] == "mock"
    assert body["embedding_model_name"] == "mock-embedding"
    assert body["embedding_dimensions"] == 3
    assert body["items"][0]["chunk_id"] == target_chunk_id
    assert body["items"][0]["title"] == "보증금 반환 문서"
    assert body["items"][0]["rank"] == 1
    assert body["items"][0]["metadata"]["document_type"] == "statute"

    with rag_client_context.session_factory() as db:
        rag_run = db.get(RagRun, body["run_id"])
        retrieval_count = (
            db.query(RagRetrieval)
            .filter(RagRetrieval.rag_run_id == body["run_id"])
            .count()
        )
        assert rag_run is not None
        assert rag_run.run_type == "search"
        assert rag_run.status == "completed"
        assert rag_run.embedding_profile_id == profile_id
        assert retrieval_count == 1


def test_rag_search_endpoint_supports_embedding_profile_and_document_filters(
    rag_client_context: ApiTestContext,
) -> None:
    register_and_login(rag_client_context.client, email="profile-rag@example.com")
    with rag_client_context.session_factory() as db:
        default_profile = _create_profile(
            db,
            dimensions=3,
            model_name="default-embedding",
            is_default=True,
        )
        selected_profile = _create_profile(
            db,
            dimensions=3,
            model_name="selected-embedding",
            is_default=False,
        )
        _create_chunk_embedding(
            db,
            profile=default_profile,
            title="기본 프로필 문서",
            heading="제1조",
            content="기본 프로필 검색 후보",
            embedding=[1.0, 0.0, 0.0],
            document_type="statute",
        )
        case_embedding = _create_chunk_embedding(
            db,
            profile=selected_profile,
            title="선택 프로필 판례",
            heading="판단",
            content="선택한 프로필과 판례 필터 검색 후보",
            embedding=[1.0, 0.0, 0.0],
            document_type="case",
        )
        selected_profile_id = selected_profile.id
        case_chunk_id = case_embedding.chunk_id
        db.commit()

    response = rag_client_context.client.post(
        "/api/rag/search",
        json={
            "query": "선택한 프로필 검색",
            "top_k": 5,
            "embedding_profile_id": selected_profile_id,
            "filters": {"document_types": ["case"]},
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["embedding_profile_id"] == selected_profile_id
    assert [item["chunk_id"] for item in body["items"]] == [case_chunk_id]
    assert body["items"][0]["metadata"]["document_type"] == "case"


def test_rag_search_endpoint_applies_top_k_per_planned_issue(
    monkeypatch: pytest.MonkeyPatch,
    rag_client_context: ApiTestContext,
) -> None:
    register_and_login(rag_client_context.client, email="issue-top-k@example.com")
    first_issue_query = "body burial concealment"
    second_issue_query = "surrender mitigation"
    with rag_client_context.session_factory() as db:
        profile = _create_profile(db, dimensions=8)
        first_embedding = _create_chunk_embedding(
            db,
            profile=profile,
            title="Body concealment statute",
            heading="Article A",
            content="body concealment issue",
            embedding=_mock_embedding_for_text(first_issue_query, dimensions=8),
        )
        second_embedding = _create_chunk_embedding(
            db,
            profile=profile,
            title="Surrender mitigation statute",
            heading="Article B",
            content="voluntary surrender issue",
            embedding=_mock_embedding_for_text(second_issue_query, dimensions=8),
        )
        first_chunk_id = first_embedding.chunk_id
        second_chunk_id = second_embedding.chunk_id
        db.commit()

    def fake_plan_legal_source_candidates(**_: object) -> LegalSourcePlan:
        return LegalSourcePlan(
            issues=[
                PlannedLegalIssue(
                    issue_key="body_concealment",
                    title="Body concealment",
                    description=None,
                    internal_rag_query=first_issue_query,
                ),
                PlannedLegalIssue(
                    issue_key="surrender",
                    title="Surrender",
                    description=None,
                    internal_rag_query=second_issue_query,
                ),
            ]
        )

    monkeypatch.setattr(
        "app.services.rag.issue_retrieval.plan_legal_source_candidates",
        fake_plan_legal_source_candidates,
    )

    response = rag_client_context.client.post(
        "/api/rag/search",
        json={
            "query": "A buried a body and later surrendered.",
            "top_k": 1,
            "filters": {"document_type": "statute"},
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["chunk_id"] for item in body["items"]] == [
        first_chunk_id,
        second_chunk_id,
    ]
    assert [item["metadata"]["planned_issue_key"] for item in body["items"]] == [
        "body_concealment",
        "surrender",
    ]


def test_rag_search_endpoint_creates_default_embedding_profile_when_missing(
    rag_client_context: ApiTestContext,
) -> None:
    register_and_login(rag_client_context.client, email="bootstrap-rag@example.com")

    response = rag_client_context.client.post(
        "/api/rag/search",
        json={
            "query": "fresh database search",
            "top_k": 3,
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["embedding_provider"] == "mock"
    assert body["embedding_model_name"] == "mock-embedding"
    assert body["embedding_dimensions"] == 3
    assert body["items"] == []

    with rag_client_context.session_factory() as db:
        profiles = embedding_repository.list_active_embedding_profiles(db)
        assert len(profiles) == 1
        assert profiles[0].is_default is True


def test_rag_search_endpoint_syncs_official_source_when_search_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    law_open_api_rag_client_context: ApiTestContext,
) -> None:
    sync_calls: list[str] = []
    register_and_login(
        law_open_api_rag_client_context.client,
        email="sync-rag@example.com",
    )

    def fake_sync_and_embed_law_open_api_statute(
        db: Session,
        *,
        query: str,
        embedding_profile: EmbeddingProfile,
        **_: object,
    ) -> SimpleNamespace:
        sync_calls.append(query)
        _create_chunk_embedding(
            db,
            profile=embedding_profile,
            title="synced statute",
            heading="Article 1",
            content=f"synced content for {query}",
            embedding=_mock_embedding_for_text(query, dimensions=3),
        )
        return SimpleNamespace(status="embedded")

    monkeypatch.setattr(
        "app.services.rag.issue_retrieval.sync_and_embed_law_open_api_statute",
        fake_sync_and_embed_law_open_api_statute,
    )

    response = law_open_api_rag_client_context.client.post(
        "/api/rag/search",
        json={
            "query": "official source sync query",
            "top_k": 3,
            "filters": {"document_type": "statute"},
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert sync_calls == ["official source sync query"]
    assert [item["title"] for item in body["items"]] == ["synced statute"]
    assert body["embedding_provider"] == "mock"


def test_rag_search_endpoint_syncs_when_existing_results_are_low_relevance(
    monkeypatch: pytest.MonkeyPatch,
    law_open_api_rag_client_context: ApiTestContext,
) -> None:
    user_query = "lease deposit return dispute"
    sync_calls: list[tuple[str, list[str] | None]] = []
    register_and_login(
        law_open_api_rag_client_context.client,
        email="low-relevance-rag@example.com",
    )
    with law_open_api_rag_client_context.session_factory() as db:
        profile = _create_profile(db, dimensions=3)
        _create_chunk_embedding(
            db,
            profile=profile,
            title="Wrong low-score statute",
            heading="Article 1",
            content="This chunk is unrelated to the lease dispute.",
            embedding=[0.0, 0.0, 0.0],
        )
        db.commit()

    def fake_plan_legal_source_candidates(**_: object) -> LegalSourcePlan:
        return LegalSourcePlan(
            candidates=[
                LegalSourceCandidate(
                    document_type="statute",
                    title="Residential Lease Protection Act",
                    query="Residential Lease Protection Act",
                    reason="lease deposit issue",
                )
            ]
        )

    def fake_sync_and_embed_law_open_api_statute(
        db: Session,
        *,
        query: str,
        embedding_profile: EmbeddingProfile,
        preferred_titles: list[str] | None = None,
        **_: object,
    ) -> SimpleNamespace:
        sync_calls.append((query, preferred_titles))
        _create_chunk_embedding(
            db,
            profile=embedding_profile,
            title="Residential Lease Protection Act",
            heading="Article 3",
            content="The landlord must return the lease deposit after termination.",
            embedding=_mock_embedding_for_text(user_query, dimensions=3),
        )
        return SimpleNamespace(status="embedded")

    monkeypatch.setattr(
        "app.services.rag.issue_retrieval.plan_legal_source_candidates",
        fake_plan_legal_source_candidates,
    )
    monkeypatch.setattr(
        "app.services.rag.issue_retrieval.sync_and_embed_law_open_api_statute",
        fake_sync_and_embed_law_open_api_statute,
    )

    response = law_open_api_rag_client_context.client.post(
        "/api/rag/search",
        json={
            "query": user_query,
            "top_k": 5,
            "filters": {"document_type": "statute"},
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert sync_calls == [
        (
            "Residential Lease Protection Act",
            ["Residential Lease Protection Act"],
        )
    ]
    assert [item["title"] for item in body["items"]] == [
        "Residential Lease Protection Act"
    ]
    assert all(item["score"] >= 0.4 for item in body["items"])


def test_rag_search_endpoint_requires_authentication_and_origin(
    rag_client_context: ApiTestContext,
) -> None:
    payload = {"query": "인증 테스트 검색"}

    unauthenticated_response = rag_client_context.client.post(
        "/api/rag/search",
        json=payload,
        headers=origin_headers(),
    )
    assert unauthenticated_response.status_code == 401

    register_and_login(rag_client_context.client, email="origin-rag@example.com")
    missing_origin_response = rag_client_context.client.post(
        "/api/rag/search",
        json=payload,
    )
    assert missing_origin_response.status_code == 403


def test_rag_search_api_is_disabled_when_ai_rag_is_disabled(
    disabled_rag_client_context: ApiTestContext,
) -> None:
    register_and_login(disabled_rag_client_context.client)

    response = disabled_rag_client_context.client.post(
        "/api/rag/search",
        json={"query": "비활성화 테스트 검색"},
        headers=origin_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "AI/RAG API is disabled"


def test_rag_search_validation_rejects_bad_options(
    rag_client_context: ApiTestContext,
) -> None:
    register_and_login(rag_client_context.client)

    response = rag_client_context.client.post(
        "/api/rag/search",
        json={
            "query": "검증 테스트 검색",
            "top_k": 0,
            "score_threshold": 1.5,
            "max_chunks_per_document": 0,
        },
        headers=origin_headers(),
    )

    assert response.status_code == 422


def test_rag_search_provider_failure_does_not_expose_raw_error(
    rag_client_context: ApiTestContext,
) -> None:
    register_and_login(rag_client_context.client)
    with rag_client_context.session_factory() as db:
        profile = _create_profile(
            db,
            dimensions=3,
            provider="mismatch-provider",
            is_default=True,
        )
        _create_chunk_embedding(
            db,
            profile=profile,
            title="provider 실패 문서",
            heading="제1조",
            content="provider 실패 검색 후보",
            embedding=[1.0, 0.0, 0.0],
        )
        db.commit()

    response = rag_client_context.client.post(
        "/api/rag/search",
        json={"query": "provider 실패 테스트", "top_k": 1},
        headers=origin_headers(),
    )

    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["error_code"] == "RetrievalResponseValidationError"
    assert body["detail"]["message"] == "RetrievalResponseValidationError"
    assert "mismatch" not in response.text


def _client_context(
    settings: Settings,
) -> Generator[ApiTestContext, None, None]:
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
        return settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    with TestClient(app) as test_client:
        yield ApiTestContext(client=test_client, session_factory=TestingSessionLocal)
    app.dependency_overrides.clear()


def _settings(*, ai_rag_enabled: bool, law_open_api_oc: str = "") -> Settings:
    return Settings(
        app_env="test",
        ai_rag_enabled=ai_rag_enabled,
        ai_agent_provider="mock",
        ai_agent_model="agent-test-model",
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=3,
        law_open_api_oc=law_open_api_oc,
    )


def origin_headers(origin: str = FRONTEND_ORIGIN) -> dict[str, str]:
    return {"Origin": origin}


def register_and_login(
    client: TestClient,
    *,
    email: str = "rag-user@example.com",
) -> dict:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "nickname": email.split("@")[0],
        },
        headers=origin_headers(),
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
        headers=origin_headers(),
    )
    assert login_response.status_code == 200
    return login_response.json()


def _create_profile(
    db: Session,
    *,
    dimensions: int,
    provider: str = "mock",
    model_name: str = "mock-embedding",
    is_default: bool = True,
) -> EmbeddingProfile:
    return embedding_repository.get_or_create_embedding_profile(
        db,
        provider=provider,
        model_name=model_name,
        dimensions=dimensions,
        status="active",
        is_default=is_default,
    )


def _create_chunk_embedding(
    db: Session,
    *,
    profile: EmbeddingProfile,
    title: str,
    heading: str,
    content: str,
    embedding: list[float],
    document_type: str = "statute",
) -> LegalDocumentChunkEmbedding:
    source = LegalSource(
        provider="fixture",
        source_type=document_type,
        external_id=None,
        source_url=f"https://example.test/{document_type}",
    )
    legal_documents.add_legal_source(db, source)
    db.flush()

    document = LegalDocument(
        source_id=source.id,
        document_type=document_type,
        title=title,
        canonical_id=f"{document_type.upper()}-{db.query(LegalDocument).count() + 1}",
        version_label="2026-01-01",
        published_date=date(2025, 12, 1),
        effective_date=date(2026, 1, 1),
        raw_text=content,
        normalized_text=content,
        raw_checksum=calculate_text_checksum(content),
        normalized_checksum=calculate_text_checksum(content),
        dedup_status="unique",
        conflict_status="none",
        index_status="embedded",
    )
    legal_documents.add_legal_document(db, document)
    db.flush()

    chunk = LegalDocumentChunk(
        document_id=document.id,
        chunk_index=0,
        heading=heading,
        content=content,
        token_count=10,
        metadata_json={"fixture": "rag_api"},
    )
    document_chunks.add_document_chunk(db, chunk)
    db.flush()

    chunk_embedding = LegalDocumentChunkEmbedding(
        chunk_id=chunk.id,
        embedding_profile_id=profile.id,
        embedding=embedding,
        embedding_status="embedded",
        content_checksum=calculate_text_checksum(content),
    )
    embedding_repository.add_chunk_embedding(db, chunk_embedding)
    db.flush()
    return chunk_embedding


def _mock_embedding_for_text(text: str, *, dimensions: int) -> list[float]:
    seed = sum(text.encode("utf-8"))
    return [((seed + index) % 100) / 100 for index in range(dimensions)]
