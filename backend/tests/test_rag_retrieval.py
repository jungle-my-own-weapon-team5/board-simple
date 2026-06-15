from collections.abc import Generator
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import LegalDocument, LegalDocumentChunk, LegalSource, User
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding
from app.models.rag_run import RagRun
from app.repositories import (
    document_chunks,
    embeddings as embedding_repository,
    legal_documents,
    rag_runs,
)
from app.services.ai.errors import ProviderUnavailableError
from app.services.ai.types import EmbeddingRequest, EmbeddingResult
from app.services.rag.normalization import calculate_text_checksum
from app.services.rag.retrieval import search_legal_documents


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


def test_search_legal_documents_returns_ranked_chunks_and_persists_audit(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    first_chunk_embedding = _create_chunk_embedding(
        db,
        profile=profile,
        title="손해배상 테스트 문서",
        heading="제1조",
        content="손해배상 책임에 관한 조문",
        embedding=[1.0, 0.0, 0.0],
    )
    second_chunk_embedding = _create_chunk_embedding(
        db,
        profile=profile,
        title="계약 해제 테스트 문서",
        heading="제2조",
        content="계약 해제와 원상회복에 관한 조문",
        embedding=[0.5, 0.5, 0.0],
    )
    _create_chunk_embedding(
        db,
        profile=profile,
        title="형사 처벌 테스트 문서",
        heading="제3조",
        content="형사 처벌에 관한 조문",
        embedding=[0.0, 1.0, 0.0],
    )

    result = search_legal_documents(
        db,
        user_id=user.id,
        query="손해배상 책임",
        embedding_profile=profile,
        ai_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
        top_k=2,
        prompt_version="v-test",
    )

    assert result.status == "completed"
    assert result.run_id is not None
    assert result.embedding_profile_id == profile.id
    assert [item.chunk_embedding_id for item in result.results] == [
        first_chunk_embedding.id,
        second_chunk_embedding.id,
    ]
    assert [item.rank for item in result.results] == [1, 2]
    assert result.results[0].score == pytest.approx(1.0)
    assert result.results[1].score == pytest.approx(0.707106, rel=1e-5)
    assert result.results[0].title == "손해배상 테스트 문서"
    assert result.results[0].source_url == "https://example.test/statute"

    rag_run = rag_runs.get_rag_run(db, result.run_id)
    retrievals = rag_runs.list_retrievals_by_run(db, result.run_id)
    assert rag_run.status == "completed"
    assert rag_run.run_type == "search"
    assert rag_run.agent_provider is None
    assert rag_run.agent_model_name is None
    assert rag_run.embedding_profile_id == profile.id
    assert rag_run.embedding_model_name == "mock-embedding"
    assert rag_run.prompt_version == "v-test"
    assert [retrieval.chunk_embedding_id for retrieval in retrievals] == [
        first_chunk_embedding.id,
        second_chunk_embedding.id,
    ]
    assert [retrieval.retrieval_type for retrieval in retrievals] == ["vector", "vector"]


def test_search_legal_documents_uses_only_selected_embedding_profile(
    db: Session,
) -> None:
    user = _create_user(db)
    selected_profile = _create_profile(db, model_name="mock-selected", dimensions=3)
    other_profile = _create_profile(db, model_name="mock-other", dimensions=3)
    selected_embedding = _create_chunk_embedding(
        db,
        profile=selected_profile,
        title="선택한 profile 문서",
        heading="제1조",
        content="선택한 검색 공간의 문서",
        embedding=[0.8, 0.2, 0.0],
    )
    _create_chunk_embedding(
        db,
        profile=other_profile,
        title="다른 profile 문서",
        heading="제2조",
        content="다른 검색 공간의 문서",
        embedding=[1.0, 0.0, 0.0],
    )

    result = search_legal_documents(
        db,
        user_id=user.id,
        query="검색 공간 격리",
        embedding_profile=selected_profile,
        ai_client=_StaticEmbeddingClient(
            [1.0, 0.0, 0.0],
            model_name="mock-selected",
        ),
        top_k=5,
    )

    assert [item.chunk_embedding_id for item in result.results] == [selected_embedding.id]


def test_search_legal_documents_filters_document_type_and_unsearchable_rows(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    searchable_embedding = _create_chunk_embedding(
        db,
        profile=profile,
        title="검색 가능 문서",
        heading="제1조",
        content="검색 가능한 법령 조문",
        embedding=[1.0, 0.0, 0.0],
        document_type="statute",
    )
    _create_chunk_embedding(
        db,
        profile=profile,
        title="실패 row 문서",
        heading="제2조",
        content="embedding 실패 문서",
        embedding=[1.0, 0.0, 0.0],
        embedding_status="failed",
        document_type="statute",
    )
    stale_embedding = _create_chunk_embedding(
        db,
        profile=profile,
        title="stale row 문서",
        heading="제3조",
        content="변경 전 본문",
        embedding=[1.0, 0.0, 0.0],
        document_type="statute",
    )
    stale_embedding.chunk.content = "변경 후 본문"
    _create_chunk_embedding(
        db,
        profile=profile,
        title="다른 문서 유형",
        heading="판단",
        content="판례 문서",
        embedding=[1.0, 0.0, 0.0],
        document_type="case",
    )
    db.flush()

    result = search_legal_documents(
        db,
        user_id=user.id,
        query="검색 가능한 법령",
        embedding_profile=profile,
        ai_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
        top_k=5,
        document_types=["statute"],
    )

    assert [item.chunk_embedding_id for item in result.results] == [
        searchable_embedding.id
    ]


def test_search_legal_documents_provider_failure_marks_rag_run_failed(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    _create_chunk_embedding(
        db,
        profile=profile,
        title="검색 후보 문서",
        heading="제1조",
        content="검색 후보",
        embedding=[1.0, 0.0, 0.0],
    )

    result = search_legal_documents(
        db,
        user_id=user.id,
        query="provider 실패 테스트",
        embedding_profile=profile,
        ai_client=_ProviderFailureClient(),
    )

    rag_run = rag_runs.get_rag_run(db, result.run_id)
    assert result.status == "failed"
    assert result.results == []
    assert result.error_code == "ProviderUnavailableError"
    assert rag_run.status == "failed"
    assert rag_run.error_code == "ProviderUnavailableError"
    assert rag_runs.list_retrievals_by_run(db, result.run_id) == []


def test_search_legal_documents_query_embedding_mismatch_marks_rag_run_failed(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)

    result = search_legal_documents(
        db,
        user_id=user.id,
        query="차원 불일치 테스트",
        embedding_profile=profile,
        ai_client=_DimensionMismatchClient(),
    )

    rag_run = rag_runs.get_rag_run(db, result.run_id)
    assert result.status == "failed"
    assert result.error_code == "RetrievalResponseValidationError"
    assert "dimensions mismatch" in (result.error_message or "")
    assert rag_run.status == "failed"


def test_search_legal_documents_rejects_invalid_input_without_rag_run(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)

    with pytest.raises(ValueError, match="query must not be blank"):
        search_legal_documents(
            db,
            user_id=user.id,
            query=" ",
            embedding_profile=profile,
            ai_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
        )
    with pytest.raises(ValueError, match="top_k must be positive"):
        search_legal_documents(
            db,
            user_id=user.id,
            query="테스트",
            embedding_profile=profile,
            ai_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
            top_k=0,
        )

    assert db.query(RagRun).count() == 0


def test_search_legal_documents_rejects_inactive_embedding_profile(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3, status="deprecated")

    with pytest.raises(ValueError, match="embedding_profile must be active"):
        search_legal_documents(
            db,
            user_id=user.id,
            query="테스트",
            embedding_profile=profile,
            ai_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
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


class _ProviderFailureClient:
    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        raise ProviderUnavailableError("provider unavailable")


class _DimensionMismatchClient:
    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(
                embedding=[0.1, 0.2, 0.3, 0.4],
                embedding_provider="mock",
                embedding_model_name=request.model,
                dimensions=4,
                input_index=0,
            )
        ]


def _create_user(db: Session) -> User:
    user = User(
        email=f"user-{db.query(User).count()}@example.com",
        password_hash="hashed-password",
        nickname=f"retrieval-user-{db.query(User).count()}",
    )
    db.add(user)
    db.flush()
    return user


def _create_profile(
    db: Session,
    *,
    model_name: str = "mock-embedding",
    dimensions: int,
    status: str = "active",
) -> EmbeddingProfile:
    return embedding_repository.get_or_create_embedding_profile(
        db,
        provider="mock",
        model_name=model_name,
        dimensions=dimensions,
        status=status,
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
    embedding_status: str = "embedded",
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
        metadata_json={"fixture": "retrieval"},
    )
    document_chunks.add_document_chunk(db, chunk)
    db.flush()
    chunk_embedding = LegalDocumentChunkEmbedding(
        chunk_id=chunk.id,
        embedding_profile_id=profile.id,
        embedding=embedding,
        embedding_status=embedding_status,
        content_checksum=calculate_text_checksum(content),
    )
    embedding_repository.add_chunk_embedding(db, chunk_embedding)
    db.flush()
    return chunk_embedding
