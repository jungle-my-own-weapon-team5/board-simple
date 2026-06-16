"""국가법령정보 Open API 문서를 RAG corpus와 동기화하는 service입니다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.models.document_chunk import LegalDocumentChunk
from app.models.embedding import EmbeddingProfile
from app.models.legal_document import LegalDocument
from app.models.legal_source import LegalSource
from app.repositories import document_chunks as chunk_repository
from app.repositories import embeddings as embedding_repository
from app.repositories import legal_documents as document_repository
from app.services.rag.ingestion import (
    IngestLegalDocumentInput,
    IngestLegalDocumentResult,
    ingest_legal_document,
)
from app.services.rag.legal_open_api import (
    LawOpenApiDocumentMetadata,
    LawOpenApiLawBody,
    LawOpenApiSearchResult,
)
from app.services.rag.normalization import calculate_text_checksum

LegalOpenApiSyncStatus = Literal[
    "not_found",
    "reused",
    "needs_embedding",
    "ingested",
]


class LawOpenApiSyncClient(Protocol):
    """동기화 service가 사용하는 국가법령정보 client의 최소 계약입니다."""

    def search(
        self,
        *,
        query: str,
        target: Literal["statute"],
        limit: int = 5,
        page: int = 1,
        search_scope: int = 1,
    ) -> LawOpenApiSearchResult:
        """목록 API에서 preflight metadata 후보를 조회합니다."""

    def get_law_body(
        self,
        *,
        mst: str | None = None,
        law_id: str | None = None,
    ) -> LawOpenApiLawBody:
        """본문 API에서 법령 전문을 조회합니다."""


@dataclass(frozen=True)
class LegalOpenApiSyncResult:
    """국가법령정보 동기화 결과입니다."""

    status: LegalOpenApiSyncStatus
    preflight_metadata: LawOpenApiDocumentMetadata | None
    document: LegalDocument | None = None
    source: LegalSource | None = None
    chunks: list[LegalDocumentChunk] | None = None
    ingestion_result: IngestLegalDocumentResult | None = None
    body_fetched: bool = False
    embeddings_reusable: bool = False
    skipped_reason: str | None = None


def sync_law_open_api_statute(
    db: Session,
    *,
    client: LawOpenApiSyncClient,
    query: str,
    embedding_profile: EmbeddingProfile | None = None,
    search_limit: int = 1,
    commit: bool = True,
) -> LegalOpenApiSyncResult:
    """현행법령 1건을 preflight 후 필요할 때만 본문 조회/ingestion합니다.

    같은 canonical/version 문서가 이미 indexed 상태이면 전문을 다시 내려받지 않습니다.
    embedding profile이 주어졌고 기존 chunk embedding이 최신이면 완전 재사용, 최신이
    아니면 기존 문서를 반환하면서 embedding 보강이 필요하다고 알려줍니다.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if search_limit <= 0:
        raise ValueError("search_limit must be positive")

    metadata = _get_first_statute_metadata(
        client.search(
            query=query,
            target="statute",
            limit=search_limit,
            page=1,
            search_scope=1,
        )
    )
    if metadata is None:
        return LegalOpenApiSyncResult(
            status="not_found",
            preflight_metadata=None,
            skipped_reason="metadata_not_found",
        )

    indexed_document = document_repository.find_indexed_document_by_identity(
        db,
        document_type=metadata.document_type,
        canonical_id=metadata.canonical_id,
        version_label=metadata.version_label,
        effective_date=metadata.effective_date,
        published_date=metadata.published_date,
    )
    if indexed_document is not None:
        return _reuse_indexed_document_if_possible(
            db,
            document=indexed_document,
            preflight_metadata=metadata,
            embedding_profile=embedding_profile,
        )

    body = client.get_law_body(
        mst=metadata.external_id,
        law_id=metadata.canonical_id,
    )
    ingestion_result = ingest_legal_document(
        db,
        _build_ingestion_input(metadata=metadata, body=body),
        commit=commit,
    )
    return LegalOpenApiSyncResult(
        status="ingested",
        preflight_metadata=metadata,
        document=ingestion_result.document,
        source=ingestion_result.source,
        chunks=ingestion_result.chunks,
        ingestion_result=ingestion_result,
        body_fetched=True,
        embeddings_reusable=False,
    )


def _get_first_statute_metadata(
    result: LawOpenApiSearchResult,
) -> LawOpenApiDocumentMetadata | None:
    for item in result.items:
        if item.preflight_metadata is not None:
            return item.preflight_metadata
    return None


def _reuse_indexed_document_if_possible(
    db: Session,
    *,
    document: LegalDocument,
    preflight_metadata: LawOpenApiDocumentMetadata,
    embedding_profile: EmbeddingProfile | None,
) -> LegalOpenApiSyncResult:
    chunks = chunk_repository.list_chunks_by_document(db, document.id)
    if embedding_profile is None or _has_fresh_chunk_embeddings(
        db,
        chunks=chunks,
        embedding_profile=embedding_profile,
    ):
        return LegalOpenApiSyncResult(
            status="reused",
            preflight_metadata=preflight_metadata,
            document=document,
            source=document.source,
            chunks=chunks,
            body_fetched=False,
            embeddings_reusable=embedding_profile is not None,
        )

    return LegalOpenApiSyncResult(
        status="needs_embedding",
        preflight_metadata=preflight_metadata,
        document=document,
        source=document.source,
        chunks=chunks,
        body_fetched=False,
        embeddings_reusable=False,
        skipped_reason="embedding_not_fresh",
    )


def _has_fresh_chunk_embeddings(
    db: Session,
    *,
    chunks: list[LegalDocumentChunk],
    embedding_profile: EmbeddingProfile,
) -> bool:
    if embedding_profile.id is None or not chunks:
        return False

    for chunk in chunks:
        chunk_embedding = embedding_repository.find_chunk_embedding(
            db,
            chunk_id=chunk.id,
            embedding_profile_id=embedding_profile.id,
        )
        if chunk_embedding is None:
            return False
        if chunk_embedding.embedding_status != "embedded":
            return False
        if chunk_embedding.content_checksum != calculate_text_checksum(chunk.content):
            return False
    return True


def _build_ingestion_input(
    *,
    metadata: LawOpenApiDocumentMetadata,
    body: LawOpenApiLawBody,
) -> IngestLegalDocumentInput:
    body_metadata = dict(body.metadata_json)
    body_metadata["preflight"] = metadata.metadata_json
    return IngestLegalDocumentInput(
        provider=metadata.provider,
        source_type=metadata.document_type,
        document_type=metadata.document_type,
        title=body.title or metadata.title,
        raw_text=body.raw_text,
        canonical_id=body.law_id or metadata.canonical_id,
        version_label=body.version_label or metadata.version_label,
        published_date=body.published_date or metadata.published_date,
        effective_date=body.effective_date or metadata.effective_date,
        source_url=body.source_url or metadata.source_url,
        external_id=body.external_id or metadata.external_id,
        fetched_at=datetime.now(timezone.utc),
        metadata_json=body_metadata,
    )
