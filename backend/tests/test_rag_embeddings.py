from collections.abc import Generator
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    LegalDocument,
    LegalDocumentChunk,
    LegalSource,
)
from app.models.embedding import EmbeddingProfile
from app.repositories import (
    document_chunks,
    embeddings as embedding_repository,
    legal_documents,
)
from app.services.ai.client import AIClient
from app.services.ai.errors import ProviderUnavailableError
from app.services.ai.types import EmbeddingRequest, EmbeddingResult
from app.services.rag.embeddings import embed_document_chunks
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


def test_embed_document_chunks_with_mock_provider(db: Session) -> None:
    document = _create_document_with_chunks(db)
    profile = _create_profile(db, dimensions=8)

    result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )

    chunk_embeddings = embedding_repository.list_chunk_embeddings_by_profile(
        db, profile.id
    )
    assert result.requested_count == 2
    assert result.embedded_count == 2
    assert result.failed_count == 0
    assert [row.embedding_status for row in chunk_embeddings] == ["embedded", "embedded"]
    assert [len(row.embedding or []) for row in chunk_embeddings] == [8, 8]
    assert chunk_embeddings[0].embedding_error is None
    assert chunk_embeddings[0].metadata_json["embedding_provider"] == "mock"
    assert chunk_embeddings[0].metadata_json["embedding_model_name"] == "mock-embedding"


def test_embed_document_chunks_does_not_duplicate_existing_embedding(
    db: Session,
) -> None:
    document = _create_document_with_chunks(db)
    profile = _create_profile(db, dimensions=8)

    embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )
    second_result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )

    chunk_embeddings = embedding_repository.list_chunk_embeddings_by_profile(
        db, profile.id
    )
    assert len(chunk_embeddings) == 2
    assert second_result.embedded_count == 0
    assert second_result.skipped_count == 2
    assert second_result.already_embedded_count == 2


def test_same_chunks_can_be_embedded_with_multiple_profiles(db: Session) -> None:
    document = _create_document_with_chunks(db)
    small_profile = _create_profile(db, model_name="mock-small", dimensions=4)
    large_profile = _create_profile(db, model_name="mock-large", dimensions=6)

    embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=small_profile,
        ai_client=_mock_ai_client(model_name="mock-small", dimensions=4),
    )
    embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=large_profile,
        ai_client=_mock_ai_client(model_name="mock-large", dimensions=6),
    )

    first_chunk_embeddings = embedding_repository.list_chunk_embeddings_by_chunk(
        db, document.chunks[0].id
    )
    assert [row.embedding_profile.dimensions for row in first_chunk_embeddings] == [4, 6]
    assert [len(row.embedding or []) for row in first_chunk_embeddings] == [4, 6]


def test_duplicate_document_is_skipped_without_embedding_rows(db: Session) -> None:
    document = _create_document_with_chunks(db, dedup_status="duplicate")
    profile = _create_profile(db, dimensions=8)

    result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )

    assert result.skipped_reason == "duplicate_document"
    assert result.skipped_count == 2
    assert embedding_repository.list_chunk_embeddings_by_profile(db, profile.id) == []


def test_conflict_document_is_skipped_without_embedding_rows(db: Session) -> None:
    document = _create_document_with_chunks(db, conflict_status="review_required")
    profile = _create_profile(db, dimensions=8)

    result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )

    assert result.skipped_reason == "document_conflict"
    assert result.skipped_count == 2
    assert embedding_repository.list_chunk_embeddings_by_profile(db, profile.id) == []


def test_provider_failure_marks_chunk_embeddings_as_failed(db: Session) -> None:
    document = _create_document_with_chunks(db)
    profile = _create_profile(db, dimensions=8)

    failed_result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_ProviderFailureClient(),
    )
    skipped_result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )
    retried_result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
        retry_failed=True,
    )

    assert failed_result.failed_count == 2
    assert skipped_result.skipped_failed_count == 2
    assert skipped_result.embedded_count == 0
    assert retried_result.embedded_count == 2
    assert [
        row.embedding_status
        for row in embedding_repository.list_chunk_embeddings_by_profile(db, profile.id)
    ] == ["embedded", "embedded"]


def test_dimension_mismatch_marks_chunk_embeddings_as_failed(db: Session) -> None:
    document = _create_document_with_chunks(db)
    profile = _create_profile(db, dimensions=8)

    result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_DimensionMismatchClient(),
    )

    chunk_embeddings = embedding_repository.list_chunk_embeddings_by_profile(
        db, profile.id
    )
    assert result.failed_count == 2
    assert [row.embedding_status for row in chunk_embeddings] == ["failed", "failed"]
    assert "dimensions mismatch" in (chunk_embeddings[0].embedding_error or "")


def test_result_count_mismatch_marks_chunk_embeddings_as_failed(db: Session) -> None:
    document = _create_document_with_chunks(db)
    profile = _create_profile(db, dimensions=8)

    result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_CountMismatchClient(),
    )

    chunk_embeddings = embedding_repository.list_chunk_embeddings_by_profile(
        db, profile.id
    )
    assert result.failed_count == 2
    assert [row.embedding_status for row in chunk_embeddings] == ["failed", "failed"]
    assert "count mismatch" in (chunk_embeddings[0].embedding_error or "")


def test_changed_chunk_content_is_reembedded_as_stale(db: Session) -> None:
    document = _create_document_with_chunks(db, chunk_count=1)
    profile = _create_profile(db, dimensions=8)
    embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )
    chunk_embedding = embedding_repository.list_chunk_embeddings_by_profile(
        db, profile.id
    )[0]
    original_checksum = chunk_embedding.content_checksum
    original_embedding = list(chunk_embedding.embedding or [])

    document.chunks[0].content = "변경된 조문 내용"
    db.flush()
    result = embed_document_chunks(
        db,
        document_id=document.id,
        embedding_profile=profile,
        ai_client=_mock_ai_client(),
    )

    db.refresh(chunk_embedding)
    assert result.stale_count == 1
    assert result.embedded_count == 1
    assert chunk_embedding.content_checksum != original_checksum
    assert chunk_embedding.content_checksum == calculate_text_checksum("변경된 조문 내용")
    assert chunk_embedding.embedding != original_embedding
    assert chunk_embedding.embedding_status == "embedded"


def test_inactive_embedding_profile_is_rejected(db: Session) -> None:
    document = _create_document_with_chunks(db)
    profile = _create_profile(db, dimensions=8, status="deprecated")

    with pytest.raises(ValueError, match="embedding_profile must be active"):
        embed_document_chunks(
            db,
            document_id=document.id,
            embedding_profile=profile,
            ai_client=_mock_ai_client(),
        )


class _ProviderFailureClient:
    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        raise ProviderUnavailableError("provider unavailable")


class _DimensionMismatchClient:
    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(
                embedding=[0.1 for _ in range(request.dimensions + 1)],
                embedding_provider="mock",
                embedding_model_name=request.model,
                dimensions=request.dimensions + 1,
                input_index=index,
            )
            for index, _text in enumerate(request.texts)
        ]


class _CountMismatchClient:
    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(
                embedding=[0.1 for _ in range(request.dimensions)],
                embedding_provider="mock",
                embedding_model_name=request.model,
                dimensions=request.dimensions,
                input_index=0,
            )
        ]


def _mock_ai_client(
    *,
    model_name: str = "mock-embedding",
    dimensions: int = 8,
) -> AIClient:
    return AIClient(
        Settings(
            ai_rag_enabled=False,
            ai_agent_provider="mock",
            ai_embedding_provider="mock",
            ai_agent_model="mock-agent",
            ai_embedding_model=model_name,
            ai_embedding_dimensions=dimensions,
        )
    )


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


def _create_document_with_chunks(
    db: Session,
    *,
    dedup_status: str = "unique",
    conflict_status: str = "none",
    chunk_count: int = 2,
) -> LegalDocument:
    source = LegalSource(
        provider="fixture",
        source_type="statute",
        external_id=None,
        source_url="https://example.test/statute",
    )
    legal_documents.add_legal_source(db, source)
    db.flush()

    document = LegalDocument(
        source_id=source.id,
        document_type="statute",
        title="테스트 법령",
        canonical_id="LAW-EMBED",
        version_label="2026-01-01",
        published_date=date(2025, 12, 1),
        effective_date=date(2026, 1, 1),
        raw_text="제1조 원문",
        normalized_text="제1조 원문",
        raw_checksum="raw-checksum",
        normalized_checksum="normalized-checksum",
        dedup_status=dedup_status,
        conflict_status=conflict_status,
    )
    legal_documents.add_legal_document(db, document)
    db.flush()

    for index in range(chunk_count):
        chunk = LegalDocumentChunk(
            document_id=document.id,
            chunk_index=index,
            heading=f"제{index + 1}조",
            content=f"테스트 조문 내용 {index + 1}",
            token_count=12,
        )
        document_chunks.add_document_chunk(db, chunk)
    db.flush()
    db.refresh(document)
    return document
