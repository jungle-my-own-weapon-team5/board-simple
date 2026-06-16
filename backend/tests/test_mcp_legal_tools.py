from collections.abc import Generator
from datetime import date

import httpx2 as httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models import LegalDocument, LegalDocumentChunk, LegalSource, User
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding
from app.repositories import (
    document_chunks,
    embeddings as embedding_repository,
    legal_documents,
)
from app.services.ai.types import EmbeddingRequest, EmbeddingResult
from app.services.mcp.registry import create_default_registry
from app.services.mcp.server import McpJsonRpcServer
from app.services.mcp.types import McpToolCallContext
from app.services.mcp.tools.legal_open_api import _resolve_client
from app.services.rag.legal_open_api import LawOpenApiClient
from app.services.rag.normalization import calculate_text_checksum


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_search_law_open_api_calls_official_search_endpoint_and_redacts_oc() -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        params = dict(request.url.params)
        assert params["OC"] == "test-oc"
        assert params["target"] == "law"
        assert params["type"] == "JSON"
        assert params["query"] == "보증금"
        assert params["display"] == "1"
        return httpx.Response(
            200,
            json={
                "LawSearch": {
                    "totalCnt": "1",
                    "law": [
                        {
                            "법령일련번호": "001",
                            "법령명한글": "주택임대차보호법",
                            "법령상세링크": "/법령/주택임대차보호법?OC=test-oc",
                            "소관부처명": "법무부",
                        }
                    ],
                }
            },
        )

    client = LawOpenApiClient(
        oc="test-oc",
        base_url="https://law.example.test/DRF/lawSearch.do",
        transport=httpx.MockTransport(handler),
    )
    server = _create_default_server(["search_law_open_api"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "law-open-api",
            "method": "tools/call",
            "params": {
                "name": "search_law_open_api",
                "arguments": {"query": "보증금", "target": "statute", "limit": 1},
            },
        },
        context=McpToolCallContext(law_open_api_client=client),
    )

    result = response["result"]
    assert result["tool_name"] == "search_law_open_api"
    assert result["external_target"] == "law"
    assert result["total_count"] == 1
    assert result["items"][0]["external_id"] == "001"
    assert result["items"][0]["title"] == "주택임대차보호법"
    assert "[REDACTED]" in result["items"][0]["source_url"]
    assert "test-oc" not in str(result)
    assert "test-oc" in captured_urls[0]


def test_search_law_open_api_timeout_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout contains test-oc", request=request)

    client = LawOpenApiClient(
        oc="test-oc",
        base_url="https://law.example.test/DRF/lawSearch.do",
        transport=httpx.MockTransport(handler),
    )
    server = _create_default_server(["search_law_open_api"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "law-timeout",
            "method": "tools/call",
            "params": {
                "name": "search_law_open_api",
                "arguments": {"query": "보증금", "target": "statute"},
            },
        },
        context=McpToolCallContext(law_open_api_client=client),
    )

    assert response["error"]["code"] == -32603
    assert response["error"]["data"]["error_code"] == "mcp_tool_timeout"
    assert "test-oc" not in str(response)


def test_search_law_open_api_requires_oc_when_default_client_is_used() -> None:
    server = _create_default_server(["search_law_open_api"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "law-config",
            "method": "tools/call",
            "params": {
                "name": "search_law_open_api",
                "arguments": {"query": "보증금", "target": "statute"},
            },
        },
        context=McpToolCallContext(settings=_settings(law_open_api_oc="")),
    )

    assert response["error"]["code"] == -32603
    assert response["error"]["data"]["error_code"] == "mcp_tool_config_error"


def test_default_law_open_api_client_uses_configured_urls() -> None:
    settings = _settings(
        law_open_api_base_url="https://law.example.test/DRF/lawSearch.do",
        law_open_api_service_url="https://law.example.test/DRF/lawService.do",
    )

    client = _resolve_client(McpToolCallContext(settings=settings))

    assert client.base_url == "https://law.example.test/DRF/lawSearch.do"
    assert client.service_url == "https://law.example.test/DRF/lawService.do"


def test_search_legal_documents_tool_calls_retrieval_service(db: Session) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    chunk_embedding = _create_chunk_embedding(
        db,
        profile=profile,
        title="보증금 반환 문서",
        heading="제1조",
        content="임대차 보증금 반환과 지연손해금에 관한 내용",
        embedding=[1.0, 0.0, 0.0],
    )
    server = _create_default_server(["search_legal_documents"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "search-docs",
            "method": "tools/call",
            "params": {
                "name": "search_legal_documents",
                "arguments": {
                    "query": "보증금 반환",
                    "top_k": 1,
                    "filters": {"document_type": "statute"},
                },
            },
        },
        context=McpToolCallContext(
            db=db,
            user_id=user.id,
            settings=_settings(),
            ai_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
        ),
    )

    result = response["result"]
    assert result["tool_name"] == "search_legal_documents"
    assert result["status"] == "completed"
    assert result["embedding_profile_id"] == profile.id
    assert result["items"][0]["chunk_embedding_id"] == chunk_embedding.id
    assert result["items"][0]["score"] == pytest.approx(1.0)


def test_verify_citations_rejects_non_retrieved_chunk(db: Session) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    chunk_embedding = _create_chunk_embedding(
        db,
        profile=profile,
        title="인용 검증 문서",
        heading="제2조",
        content="인용 검증 대상 조문",
        embedding=[1.0, 0.0, 0.0],
    )
    server = _create_default_server(["search_legal_documents", "verify_citations"])
    search_response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "search-before-citation",
            "method": "tools/call",
            "params": {
                "name": "search_legal_documents",
                "arguments": {"query": "인용 검증", "top_k": 1},
            },
        },
        context=McpToolCallContext(
            db=db,
            user_id=user.id,
            settings=_settings(),
            ai_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
        ),
    )
    run_id = search_response["result"]["run_id"]

    verify_response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "verify-citations",
            "method": "tools/call",
            "params": {
                "name": "verify_citations",
                "arguments": {
                    "run_id": run_id,
                    "citations": [
                        {"chunk_id": chunk_embedding.chunk_id},
                        {"chunk_id": 999999},
                    ],
                },
            },
        },
        context=McpToolCallContext(db=db, user_id=user.id),
    )

    result = verify_response["result"]
    assert result["tool_name"] == "verify_citations"
    assert result["valid"] is False
    assert result["valid_citations"][0]["chunk_id"] == chunk_embedding.chunk_id
    assert result["invalid_citations"] == [
        {
            "index": 1,
            "valid": False,
            "reference_type": "chunk_id",
            "chunk_id": 999999,
            "reason": "citation_not_retrieved",
        }
    ]


def _create_default_server(allowed_tool_names: list[str]) -> McpJsonRpcServer:
    return McpJsonRpcServer(
        registry=create_default_registry(),
        allowed_tool_names=allowed_tool_names,
    )


def _settings(
    *,
    law_open_api_oc: str = "test-oc",
    law_open_api_base_url: str = "https://www.law.go.kr/DRF/lawSearch.do",
    law_open_api_service_url: str = "https://www.law.go.kr/DRF/lawService.do",
) -> Settings:
    return Settings(
        app_env="test",
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=3,
        law_open_api_oc=law_open_api_oc,
        law_open_api_base_url=law_open_api_base_url,
        law_open_api_service_url=law_open_api_service_url,
    )


class _StaticEmbeddingClient:
    def __init__(
        self,
        embedding: list[float],
        *,
        provider: str = "mock",
        model_name: str = "mock-embedding",
    ) -> None:
        self.embedding = embedding
        self.provider = provider
        self.model_name = model_name

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(
                embedding=self.embedding,
                embedding_provider=self.provider,
                embedding_model_name=self.model_name,
                dimensions=len(self.embedding),
                input_index=0,
            )
        ]


def _create_user(db: Session) -> User:
    user = User(
        email=f"mcp-legal-user-{db.query(User).count()}@example.com",
        password_hash="hashed-password",
        nickname=f"mcp-legal-user-{db.query(User).count()}",
    )
    db.add(user)
    db.flush()
    return user


def _create_profile(
    db: Session,
    *,
    dimensions: int,
) -> EmbeddingProfile:
    return embedding_repository.get_or_create_embedding_profile(
        db,
        provider="mock",
        model_name="mock-embedding",
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
    )
    legal_documents.add_legal_document(db, document)
    db.flush()
    chunk = LegalDocumentChunk(
        document_id=document.id,
        chunk_index=0,
        heading=heading,
        content=content,
        token_count=10,
        metadata_json={"fixture": "mcp_legal_tools"},
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
