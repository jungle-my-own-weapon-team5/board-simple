from collections.abc import Generator
from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.ai import get_orchestrator_agent
from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.main import app
from app.models import LegalDocument, LegalDocumentChunk, LegalSource, RagRun
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding
from app.repositories import (
    document_chunks,
    embeddings as embedding_repository,
    legal_documents,
)
from app.services.agent.state import AgentRunRequest, AgentRunResult
from app.services.rag.normalization import calculate_text_checksum

FRONTEND_ORIGIN = "http://localhost:3000"


@dataclass(frozen=True)
class ApiTestContext:
    client: TestClient
    session_factory: sessionmaker[Session]


@pytest.fixture()
def ai_client_context() -> Generator[ApiTestContext, None, None]:
    yield from _client_context(_settings(ai_rag_enabled=True))


@pytest.fixture()
def disabled_ai_client_context() -> Generator[ApiTestContext, None, None]:
    yield from _client_context(_settings(ai_rag_enabled=False))


@pytest.fixture()
def rate_limited_ai_client_context() -> Generator[ApiTestContext, None, None]:
    yield from _client_context(
        _settings(ai_rag_enabled=True, ai_rate_limit_per_minute=1)
    )


def test_answer_drafts_endpoint_runs_agent_and_returns_citations(
    ai_client_context: ApiTestContext,
) -> None:
    register_and_login(ai_client_context.client)
    with ai_client_context.session_factory() as db:
        profile = _create_profile(db, dimensions=3)
        chunk_embedding = _create_chunk_embedding(
            db,
            profile=profile,
            title="보증금 반환 문서",
            heading="제1조",
            content="임대차 보증금 반환과 지연손해금에 관한 내용",
            embedding=[1.0, 0.0, 0.0],
        )
        chunk_id = chunk_embedding.chunk_id
        db.commit()

    response = ai_client_context.client.post(
        "/api/ai/answer-drafts",
        json={
            "facts": "임대차 보증금을 돌려받지 못했습니다.",
            "question": "내용증명 초안 방향을 알려주세요.",
            "top_k": 1,
            "tone": "formal",
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["agent_provider"] == "mock"
    assert body["agent_model_name"] == "agent-test-model"
    assert body["draft"] == "Mock provider response"
    assert body["citations"] == [
            {
                "chunk_id": chunk_id,
                "title": "보증금 반환 문서",
                "source_url": "https://example.test/statute",
                "heading": "제1조",
            "rank": 1,
        }
    ]
    assert body["disclaimer"].startswith("이 결과는 법률정보 기반 초안 보조")
    assert [tool_call["tool_name"] for tool_call in body["tool_calls"]] == [
        "search_legal_documents",
        "verify_citations",
    ]

    with ai_client_context.session_factory() as db:
        rag_run = db.get(RagRun, body["run_id"])
        assert rag_run is not None
        assert rag_run.run_type == "answer_draft"
        assert rag_run.answer == "Mock provider response"
        assert rag_run.agent_provider == "mock"
        assert rag_run.agent_model_name == "agent-test-model"


def test_agent_runs_endpoint_returns_common_response_shape(
    ai_client_context: ApiTestContext,
) -> None:
    register_and_login(ai_client_context.client, email="agent-run@example.com")
    with ai_client_context.session_factory() as db:
        profile = _create_profile(db, dimensions=3)
        _create_chunk_embedding(
            db,
            profile=profile,
            title="쟁점 탐지 문서",
            heading="제2조",
            content="계약 종료와 보증금 반환 쟁점에 관한 내용",
            embedding=[1.0, 0.0, 0.0],
        )
        db.commit()

    response = ai_client_context.client.post(
        "/api/ai/agent-runs",
        json={
            "task_type": "dispute_issues",
            "facts": "계약 종료 후 보증금을 받지 못했습니다.",
            "question": "검토할 쟁점을 정리해주세요.",
            "search_mode": "issue_spotting",
            "top_k": 1,
        },
        headers=origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["task_type"] == "dispute_issues"
    assert body["result"]["draft"] == "Mock provider response"
    assert body["result"]["citations"][0]["title"] == "쟁점 탐지 문서"
    assert "error_code" not in body


def test_ai_agent_endpoints_require_authentication_and_origin(
    ai_client_context: ApiTestContext,
) -> None:
    payload = {
        "facts": "인증 테스트 사실관계",
        "question": "답변 초안을 만들어주세요.",
    }

    unauthenticated_response = ai_client_context.client.post(
        "/api/ai/answer-drafts",
        json=payload,
        headers=origin_headers(),
    )
    assert unauthenticated_response.status_code == 401

    register_and_login(ai_client_context.client, email="origin-ai@example.com")
    missing_origin_response = ai_client_context.client.post(
        "/api/ai/answer-drafts",
        json=payload,
    )
    assert missing_origin_response.status_code == 403


def test_ai_agent_api_is_disabled_when_ai_rag_is_disabled(
    disabled_ai_client_context: ApiTestContext,
) -> None:
    register_and_login(disabled_ai_client_context.client)

    response = disabled_ai_client_context.client.post(
        "/api/ai/agent-runs",
        json={
            "task_type": "answer_draft",
            "facts": "비활성화 테스트 사실관계",
            "question": "답변 초안을 만들어주세요.",
        },
        headers=origin_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "AI/RAG API is disabled"


def test_ai_agent_endpoint_rate_limits_per_user(
    rate_limited_ai_client_context: ApiTestContext,
) -> None:
    register_and_login(rate_limited_ai_client_context.client, email="rate-ai@example.com")
    app.dependency_overrides[get_orchestrator_agent] = lambda: _SuccessfulAgent()
    payload = {
        "task_type": "answer_draft",
        "facts": "rate limit 테스트 사실관계",
        "question": "답변 초안을 만들어주세요.",
    }

    first_response = rate_limited_ai_client_context.client.post(
        "/api/ai/agent-runs",
        json=payload,
        headers=origin_headers(),
    )
    second_response = rate_limited_ai_client_context.client.post(
        "/api/ai/agent-runs",
        json=payload,
        headers=origin_headers(),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["detail"] == "AI rate limit exceeded"


def test_ai_agent_endpoint_rejects_oversized_request_body(
    ai_client_context: ApiTestContext,
) -> None:
    response = ai_client_context.client.post(
        "/api/ai/agent-runs",
        json={
            "task_type": "answer_draft",
            "facts": "x" * 300_000,
            "question": "답변 초안을 만들어주세요.",
        },
        headers=origin_headers(),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large"


def test_provider_failure_is_mapped_without_raw_provider_message(
    ai_client_context: ApiTestContext,
) -> None:
    register_and_login(ai_client_context.client)
    app.dependency_overrides[get_orchestrator_agent] = lambda: _FailingAgent()

    response = ai_client_context.client.post(
        "/api/ai/agent-runs",
        json={
            "task_type": "answer_draft",
            "facts": "provider 실패 테스트 사실관계",
            "question": "답변 초안을 만들어주세요.",
        },
        headers=origin_headers(),
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["run_id"] == 77
    assert body["detail"]["error_code"] == "ProviderUnavailableError"
    assert body["detail"]["message"] == "ProviderUnavailableError"
    assert "secret-like-provider-message" not in response.text


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


def _settings(
    *,
    ai_rag_enabled: bool,
    ai_rate_limit_per_minute: int = 20,
) -> Settings:
    return Settings(
        app_env="test",
        ai_rag_enabled=ai_rag_enabled,
        ai_agent_provider="mock",
        ai_agent_model="agent-test-model",
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=3,
        ai_rate_limit_per_minute=ai_rate_limit_per_minute,
    )


class _SuccessfulAgent:
    def run(self, db: Session, request: AgentRunRequest) -> AgentRunResult:
        return AgentRunResult(
            run_id=88,
            status="completed",
            task_type=request.task_type,
            agent_provider="mock",
            agent_model_name="agent-test-model",
            answer="성공 응답입니다.",
            citations=[],
            tool_calls=[],
        )


class _FailingAgent:
    def run(self, db: Session, request: AgentRunRequest) -> AgentRunResult:
        return AgentRunResult(
            run_id=77,
            status="failed",
            task_type=request.task_type,
            agent_provider="mock",
            agent_model_name="agent-test-model",
            answer=None,
            error_code="ProviderUnavailableError",
            error_message="secret-like-provider-message",
        )


def origin_headers(origin: str = FRONTEND_ORIGIN) -> dict[str, str]:
    return {"Origin": origin}


def register_and_login(
    client: TestClient,
    *,
    email: str = "ai-user@example.com",
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
    model_name: str = "mock-embedding",
) -> EmbeddingProfile:
    return embedding_repository.get_or_create_embedding_profile(
        db,
        provider="mock",
        model_name=model_name,
        dimensions=dimensions,
        status="active",
        is_default=True,
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
        metadata_json={"fixture": "ai_api"},
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
