from collections.abc import Generator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import LegalDocument, LegalDocumentChunk, LegalSource
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding
from app.repositories import embeddings as embedding_repository
from app.services.ai.errors import ProviderUnavailableError
from app.services.ai.types import EmbeddingRequest, EmbeddingResult
from app.services.rag.legal_open_api import (
    LawOpenApiDocumentMetadata,
    LawOpenApiLawBody,
    LawOpenApiSearchItem,
    LawOpenApiSearchResult,
)
from app.services.rag.legal_open_api_sync import (
    sync_and_embed_law_open_api_statute,
    sync_law_open_api_statute,
)
from app.services.rag.normalization import calculate_text_checksum, normalize_text


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


def test_sync_reuses_indexed_document_when_embeddings_are_fresh(db: Session) -> None:
    metadata = _metadata()
    document, chunk = _create_indexed_document(db)
    profile = _create_embedding_profile(db)
    _create_chunk_embedding(
        db,
        chunk=chunk,
        profile=profile,
        content_checksum=calculate_text_checksum(chunk.content),
    )
    client = _FakeLawOpenApiClient(metadata=metadata)

    result = sync_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        embedding_profile=profile,
    )

    assert result.status == "reused"
    assert result.document.id == document.id
    assert result.chunks == [chunk]
    assert result.body_fetched is False
    assert result.embeddings_reusable is True
    assert client.body_call_count == 0
    assert db.query(LegalDocument).count() == 1


def test_sync_returns_needs_embedding_without_body_fetch_when_embedding_is_missing(
    db: Session,
) -> None:
    metadata = _metadata()
    document, chunk = _create_indexed_document(db)
    profile = _create_embedding_profile(db)
    client = _FakeLawOpenApiClient(metadata=metadata)

    result = sync_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        embedding_profile=profile,
    )

    assert result.status == "needs_embedding"
    assert result.document.id == document.id
    assert result.chunks == [chunk]
    assert result.body_fetched is False
    assert result.embeddings_reusable is False
    assert result.skipped_reason == "embedding_not_fresh"
    assert client.body_call_count == 0
    assert db.query(LegalDocument).count() == 1


def test_sync_fetches_body_and_ingests_when_indexed_document_does_not_exist(
    db: Session,
) -> None:
    metadata = _metadata()
    body = _body()
    client = _FakeLawOpenApiClient(metadata=metadata, body=body)

    result = sync_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
    )

    assert result.status == "ingested"
    assert result.body_fetched is True
    assert client.body_call_count == 1
    assert result.source.provider == "law_open_api"
    assert result.source.external_id == "123456"
    assert result.source.fetched_at is not None
    assert result.source.metadata_json["preflight"]["canonical_id"] == "001234"
    assert result.document.document_type == "statute"
    assert result.document.title == "자동차관리법"
    assert result.document.canonical_id == "001234"
    assert result.document.version_label == "2024-02-01,12345,2024-01-01"
    assert result.document.published_date == date(2024, 1, 1)
    assert result.document.effective_date == date(2024, 2, 1)
    assert result.document.index_status == "pending"
    assert result.chunks
    assert "제1조" in result.document.raw_text


def test_force_refresh_reuses_indexed_document_when_body_checksum_matches(
    db: Session,
) -> None:
    metadata = _metadata()
    body = _body()
    document, _chunk = _create_indexed_document(db, content=body.raw_text)
    client = _FakeLawOpenApiClient(metadata=metadata, body=body)

    result = sync_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        force_refresh=True,
    )

    assert result.status == "reused"
    assert result.document.id == document.id
    assert result.body_fetched is True
    assert client.body_call_count == 1
    assert db.query(LegalDocument).count() == 1


def test_force_refresh_creates_conflict_when_same_version_body_checksum_differs(
    db: Session,
) -> None:
    metadata = _metadata()
    existing_document, _chunk = _create_indexed_document(db)
    body = _body(
        raw_text="자동차관리법\n\n제1조(목적) 이 법은 변경된 본문을 가진다.",
    )
    client = _FakeLawOpenApiClient(metadata=metadata, body=body)

    result = sync_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        force_refresh=True,
    )

    assert result.status == "ingested"
    assert result.body_fetched is True
    assert result.document.id != existing_document.id
    assert result.document.conflict_status == "review_required"
    assert result.ingestion_result.conflicting_document_ids == [existing_document.id]
    assert client.body_call_count == 1
    assert db.query(LegalDocument).count() == 2


def test_sync_and_embed_reuses_fresh_embeddings_without_provider_call(
    db: Session,
) -> None:
    metadata = _metadata()
    document, chunk = _create_indexed_document(db)
    profile = _create_embedding_profile(db)
    _create_chunk_embedding(
        db,
        chunk=chunk,
        profile=profile,
        content_checksum=calculate_text_checksum(chunk.content),
    )
    client = _FakeLawOpenApiClient(metadata=metadata)
    ai_client = _CountingEmbeddingClient()

    result = sync_and_embed_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        embedding_profile=profile,
        ai_client=ai_client,
    )

    assert result.status == "reused"
    assert result.embedding_result is None
    assert result.document.id == document.id
    assert result.embeddings_reusable is True
    assert client.body_call_count == 0
    assert ai_client.call_count == 0
    assert document.index_status == "indexed"


def test_sync_and_embed_embeds_existing_document_without_body_fetch(
    db: Session,
) -> None:
    metadata = _metadata()
    document, chunk = _create_indexed_document(db)
    profile = _create_embedding_profile(db)
    client = _FakeLawOpenApiClient(metadata=metadata)
    ai_client = _CountingEmbeddingClient()

    result = sync_and_embed_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        embedding_profile=profile,
        ai_client=ai_client,
    )

    assert result.status == "embedded"
    assert result.sync_result.status == "needs_embedding"
    assert result.embedding_result.embedded_count == 1
    assert result.document.id == document.id
    assert result.document.index_status == "indexed"
    assert result.document.indexed_at is not None
    assert result.document.index_error is None
    assert client.body_call_count == 0
    assert ai_client.call_count == 1
    chunk_embedding = embedding_repository.find_chunk_embedding(
        db,
        chunk_id=chunk.id,
        embedding_profile_id=profile.id,
    )
    assert chunk_embedding.embedding_status == "embedded"


def test_sync_and_embed_fetches_body_ingests_and_embeds_new_document(
    db: Session,
) -> None:
    metadata = _metadata()
    client = _FakeLawOpenApiClient(metadata=metadata, body=_body())
    profile = _create_embedding_profile(db)
    ai_client = _CountingEmbeddingClient()

    result = sync_and_embed_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        embedding_profile=profile,
        ai_client=ai_client,
    )

    assert result.status == "embedded"
    assert result.sync_result.status == "ingested"
    assert result.embedding_result.embedded_count == len(result.chunks)
    assert result.document.index_status == "indexed"
    assert result.document.indexed_at is not None
    assert result.document.index_error is None
    assert client.body_call_count == 1
    assert ai_client.call_count == 1
    chunk_embeddings = embedding_repository.list_chunk_embeddings_by_profile(
        db,
        profile.id,
    )
    assert len(chunk_embeddings) == len(result.chunks)
    assert {row.embedding_status for row in chunk_embeddings} == {"embedded"}


def test_sync_and_embed_marks_document_failed_when_embedding_fails(
    db: Session,
) -> None:
    metadata = _metadata()
    client = _FakeLawOpenApiClient(metadata=metadata, body=_body())
    profile = _create_embedding_profile(db)

    result = sync_and_embed_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        embedding_profile=profile,
        ai_client=_FailingEmbeddingClient(),
    )

    assert result.status == "embedding_failed"
    assert result.sync_result.status == "ingested"
    assert result.embedding_result.failed_count == len(result.chunks)
    assert result.document.index_status == "failed"
    assert result.document.indexed_at is None
    assert "embedding failed" in result.document.index_error
    assert client.body_call_count == 1
    chunk_embeddings = embedding_repository.list_chunk_embeddings_by_profile(
        db,
        profile.id,
    )
    assert len(chunk_embeddings) == len(result.chunks)
    assert {row.embedding_status for row in chunk_embeddings} == {"failed"}


def test_sync_and_embed_does_not_call_embedding_provider_for_conflict_document(
    db: Session,
) -> None:
    metadata = _metadata()
    _create_indexed_document(db)
    body = _body(
        raw_text="자동차관리법\n\n제1조(목적) 이 법은 변경된 본문을 가진다.",
    )
    client = _FakeLawOpenApiClient(metadata=metadata, body=body)
    profile = _create_embedding_profile(db)
    ai_client = _CountingEmbeddingClient()

    result = sync_and_embed_law_open_api_statute(
        db,
        client=client,
        query="자동차관리법",
        embedding_profile=profile,
        ai_client=ai_client,
        force_refresh=True,
    )

    assert result.status == "embedding_failed"
    assert result.sync_result.status == "ingested"
    assert result.document.conflict_status == "review_required"
    assert result.embedding_result.skipped_reason == "document_conflict"
    assert result.document.index_status == "failed"
    assert result.document.index_error == "document_conflict"
    assert client.body_call_count == 1
    assert ai_client.call_count == 0
    assert embedding_repository.list_chunk_embeddings_by_profile(db, profile.id) == []


def _metadata() -> LawOpenApiDocumentMetadata:
    return LawOpenApiDocumentMetadata(
        provider="law_open_api",
        provider_target="law",
        document_type="statute",
        title="자동차관리법",
        external_id="123456",
        canonical_id="001234",
        version_label="2024-02-01,12345,2024-01-01",
        published_date=date(2024, 1, 1),
        effective_date=date(2024, 2, 1),
        source_url="https://www.law.go.kr/법령/자동차관리법",
        metadata_json={
            "provider": "law_open_api",
            "provider_target": "law",
            "document_type": "statute",
            "external_id": "123456",
            "canonical_id": "001234",
            "version_label": "2024-02-01,12345,2024-01-01",
            "published_date": "2024-01-01",
            "effective_date": "2024-02-01",
            "source_url": "https://www.law.go.kr/법령/자동차관리법",
        },
    )


def _body(
    *,
    raw_text: str = "자동차관리법\n\n제1조(목적) 이 법은 자동차를 효율적으로 관리한다.",
) -> LawOpenApiLawBody:
    return LawOpenApiLawBody(
        title="자동차관리법",
        raw_text=raw_text,
        external_id="123456",
        law_id="001234",
        mst="123456",
        source_url="https://www.law.go.kr/법령/자동차관리법",
        published_date=date(2024, 1, 1),
        effective_date=date(2024, 2, 1),
        version_label="2024-02-01,12345,2024-01-01",
        metadata_json={
            "provider_target": "law",
            "external_id": "123456",
            "law_id": "001234",
            "mst": "123456",
        },
    )


def _create_indexed_document(
    db: Session,
    *,
    content: str = "제1조(목적) 이 법은 자동차를 효율적으로 관리한다.",
) -> tuple[LegalDocument, LegalDocumentChunk]:
    source = LegalSource(
        provider="law_open_api",
        source_type="statute",
        external_id="123456",
        source_url="https://www.law.go.kr/법령/자동차관리법",
        fetched_at=datetime.now(timezone.utc),
        metadata_json={"fixture": "sync"},
    )
    db.add(source)
    db.flush()
    normalized_content = normalize_text(content)
    document = LegalDocument(
        source_id=source.id,
        document_type="statute",
        title="자동차관리법",
        canonical_id="001234",
        version_label="2024-02-01,12345,2024-01-01",
        published_date=date(2024, 1, 1),
        effective_date=date(2024, 2, 1),
        raw_text=content,
        normalized_text=normalized_content,
        raw_checksum=calculate_text_checksum(content),
        normalized_checksum=calculate_text_checksum(normalized_content),
        dedup_status="unique",
        conflict_status="none",
        index_status="indexed",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(document)
    db.flush()
    chunk = LegalDocumentChunk(
        document_id=document.id,
        chunk_index=0,
        heading="제1조(목적)",
        content=content,
        token_count=10,
        metadata_json={"fixture": "sync"},
    )
    db.add(chunk)
    db.flush()
    return document, chunk


def _create_embedding_profile(db: Session) -> EmbeddingProfile:
    return embedding_repository.get_or_create_embedding_profile(
        db,
        provider="mock",
        model_name="mock-embedding",
        dimensions=3,
        status="active",
        is_default=True,
    )


def _create_chunk_embedding(
    db: Session,
    *,
    chunk: LegalDocumentChunk,
    profile: EmbeddingProfile,
    content_checksum: str,
) -> LegalDocumentChunkEmbedding:
    chunk_embedding = LegalDocumentChunkEmbedding(
        chunk_id=chunk.id,
        embedding_profile_id=profile.id,
        embedding=[1.0, 0.0, 0.0],
        embedding_status="embedded",
        embedded_at=datetime.now(timezone.utc),
        content_checksum=content_checksum,
    )
    db.add(chunk_embedding)
    db.flush()
    return chunk_embedding


class _CountingEmbeddingClient:
    def __init__(self) -> None:
        self.call_count = 0

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        self.call_count += 1
        return [
            EmbeddingResult(
                embedding=[1.0, *[0.0 for _ in range(request.dimensions - 1)]],
                embedding_provider="mock",
                embedding_model_name=request.model,
                dimensions=request.dimensions,
                input_index=index,
            )
            for index, _text in enumerate(request.texts)
        ]


class _FailingEmbeddingClient:
    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        raise ProviderUnavailableError("provider unavailable")


class _FakeLawOpenApiClient:
    def __init__(
        self,
        *,
        metadata: LawOpenApiDocumentMetadata,
        body: LawOpenApiLawBody | None = None,
    ) -> None:
        self.metadata = metadata
        self.body = body or _body()
        self.body_call_count = 0

    def search(
        self,
        *,
        query: str,
        target: str,
        limit: int = 5,
        page: int = 1,
        search_scope: int = 1,
    ) -> LawOpenApiSearchResult:
        assert query == "자동차관리법"
        assert target == "statute"
        assert limit >= 1
        assert page == 1
        assert search_scope == 1
        item = LawOpenApiSearchItem(
            external_id=self.metadata.external_id,
            title=self.metadata.title,
            source_url=self.metadata.source_url,
            summary=None,
            target="statute",
            metadata_json=self.metadata.metadata_json,
            preflight_metadata=self.metadata,
        )
        return LawOpenApiSearchResult(
            query=query,
            target="statute",
            external_target="law",
            page=page,
            limit=limit,
            total_count=1,
            items=[item],
        )

    def get_law_body(
        self,
        *,
        mst: str | None = None,
        law_id: str | None = None,
    ) -> LawOpenApiLawBody:
        self.body_call_count += 1
        assert mst == self.metadata.external_id
        assert law_id == self.metadata.canonical_id
        return self.body
