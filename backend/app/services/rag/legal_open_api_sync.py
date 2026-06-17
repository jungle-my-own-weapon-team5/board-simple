"""국가법령정보 Open API 문서를 RAG corpus와 동기화하는 service입니다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.models.document_chunk import LegalDocumentChunk
from app.models.embedding import EmbeddingProfile
from app.models.legal_document import LegalDocument
from app.models.legal_source import LegalSource
from app.repositories import document_chunks as chunk_repository
from app.repositories import embeddings as embedding_repository
from app.repositories import legal_documents as document_repository
from app.services.rag.chunking import CHUNKING_SCHEMA_VERSION
from app.services.rag.embeddings import (
    EmbedDocumentChunksResult,
    EmbeddingClient,
    embed_document_chunks,
)
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
from app.services.rag.normalization import calculate_text_checksum, normalize_document_text

LegalOpenApiSyncStatus = Literal[
    "not_found",
    "reused",
    "needs_embedding",
    "ingested",
]
LegalOpenApiSyncAndEmbedStatus = Literal[
    "not_found",
    "reused",
    "embedded",
    "embedding_failed",
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
    replaced_document_ids: list[int] | None = None


@dataclass(frozen=True)
class LegalOpenApiSyncAndEmbedResult:
    """preflight sync와 embedding 실행까지 포함한 결과입니다."""

    status: LegalOpenApiSyncAndEmbedStatus
    sync_result: LegalOpenApiSyncResult
    embedding_result: EmbedDocumentChunksResult | None = None
    document: LegalDocument | None = None
    source: LegalSource | None = None
    chunks: list[LegalDocumentChunk] | None = None
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
    preferred_titles: list[str] | None = None,
    force_refresh: bool = False,
    replace_existing: bool = False,
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

    metadata = _select_statute_metadata(
        client.search(
            query=query,
            target="statute",
            limit=search_limit,
            page=1,
            search_scope=1,
        ),
        preferred_titles=preferred_titles or [query],
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
    reindex_reason = _document_reindex_reason(db, indexed_document)
    should_replace_existing = replace_existing or reindex_reason is not None
    if indexed_document is not None and not force_refresh and not should_replace_existing:
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
    if indexed_document is not None and _body_matches_indexed_document(
        body,
        indexed_document,
    ) and not should_replace_existing:
        return _reuse_indexed_document_if_possible(
            db,
            document=indexed_document,
            preflight_metadata=metadata,
            embedding_profile=embedding_profile,
            body_fetched=True,
        )

    replaced_document_ids: list[int] = []
    if should_replace_existing:
        replaced_document_ids = _remove_existing_documents_for_reindex(
            db,
            metadata=metadata,
            reason="manual_reindex" if replace_existing else reindex_reason,
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
        replaced_document_ids=replaced_document_ids,
    )


def sync_and_embed_law_open_api_statute(
    db: Session,
    *,
    client: LawOpenApiSyncClient,
    query: str,
    embedding_profile: EmbeddingProfile,
    ai_client: EmbeddingClient,
    search_limit: int = 1,
    preferred_titles: list[str] | None = None,
    timeout_seconds: int = 60,
    batch_size: int = 16,
    retry_failed: bool = False,
    force_reembed: bool = False,
    force_refresh: bool = False,
    replace_existing: bool = False,
    commit: bool = True,
) -> LegalOpenApiSyncAndEmbedResult:
    """국가법령정보 법령을 검색 가능한 embedding 상태까지 동기화합니다.

    기존 indexed 문서와 최신 embedding이 있으면 외부 본문 API와 embedding provider를
    모두 호출하지 않습니다. 문서는 최신인데 embedding만 부족하면 본문 API는 생략하고
    기존 chunk에 embedding만 보강합니다.
    """
    try:
        sync_result = sync_law_open_api_statute(
            db,
            client=client,
            query=query,
            embedding_profile=embedding_profile,
            search_limit=search_limit,
            preferred_titles=preferred_titles,
            force_refresh=force_refresh,
            replace_existing=replace_existing,
            commit=False,
        )
        if sync_result.status == "not_found":
            return LegalOpenApiSyncAndEmbedResult(
                status="not_found",
                sync_result=sync_result,
                skipped_reason=sync_result.skipped_reason,
            )
        if sync_result.status == "reused":
            return LegalOpenApiSyncAndEmbedResult(
                status="reused",
                sync_result=sync_result,
                document=sync_result.document,
                source=sync_result.source,
                chunks=sync_result.chunks,
                body_fetched=sync_result.body_fetched,
                embeddings_reusable=True,
            )
        if sync_result.document is None:
            raise ValueError("sync result document is required before embedding")

        embedding_result = embed_document_chunks(
            db,
            document_id=sync_result.document.id,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            timeout_seconds=timeout_seconds,
            batch_size=batch_size,
            retry_failed=retry_failed,
            force_reembed=force_reembed,
            commit=False,
        )
        chunks = sync_result.chunks or chunk_repository.list_chunks_by_document(
            db,
            sync_result.document.id,
        )
        embeddings_are_fresh = _has_fresh_chunk_embeddings(
            db,
            chunks=chunks,
            embedding_profile=embedding_profile,
        )
        if embeddings_are_fresh:
            _mark_document_indexed(sync_result.document)
            status: LegalOpenApiSyncAndEmbedStatus = "embedded"
            skipped_reason = None
        else:
            _mark_document_index_failed(sync_result.document, embedding_result)
            status = "embedding_failed"
            skipped_reason = sync_result.document.index_error

        db.flush()
        if commit:
            db.commit()
            db.refresh(sync_result.document)
        return LegalOpenApiSyncAndEmbedResult(
            status=status,
            sync_result=sync_result,
            embedding_result=embedding_result,
            document=sync_result.document,
            source=sync_result.source,
            chunks=chunks,
            body_fetched=sync_result.body_fetched,
            embeddings_reusable=embeddings_are_fresh,
            skipped_reason=skipped_reason,
        )
    except Exception:
        if commit:
            db.rollback()
        raise


def _select_statute_metadata(
    result: LawOpenApiSearchResult,
    *,
    preferred_titles: list[str],
) -> LawOpenApiDocumentMetadata | None:
    metadata_items = [
        item.preflight_metadata
        for item in result.items
        if item.preflight_metadata is not None
    ]
    if not metadata_items:
        return None
    ranked = sorted(
        metadata_items,
        key=lambda metadata: _metadata_title_rank(metadata, preferred_titles),
    )
    return ranked[0]


def _metadata_title_rank(
    metadata: LawOpenApiDocumentMetadata,
    preferred_titles: list[str],
) -> tuple[int, int, str]:
    title = _normalize_title(metadata.title)
    preferred = [_normalize_title(value) for value in preferred_titles if value.strip()]
    for candidate in preferred:
        if title == candidate:
            return (0, len(title), title)
    for candidate in preferred:
        if title.startswith(candidate):
            return (1, len(title), title)
    for candidate in preferred:
        if candidate and candidate in title:
            return (2, len(title), title)
    for candidate in preferred:
        if title and title in candidate:
            return (3, len(title), title)
    return (4, len(title), title)


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _reuse_indexed_document_if_possible(
    db: Session,
    *,
    document: LegalDocument,
    preflight_metadata: LawOpenApiDocumentMetadata,
    embedding_profile: EmbeddingProfile | None,
    body_fetched: bool = False,
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
            body_fetched=body_fetched,
            embeddings_reusable=embedding_profile is not None,
        )

    return LegalOpenApiSyncResult(
        status="needs_embedding",
        preflight_metadata=preflight_metadata,
        document=document,
        source=document.source,
        chunks=chunks,
        body_fetched=body_fetched,
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


def _body_matches_indexed_document(
    body: LawOpenApiLawBody,
    document: LegalDocument,
) -> bool:
    normalized = normalize_document_text(body.raw_text)
    return normalized.normalized_checksum == document.normalized_checksum


def _document_reindex_reason(
    db: Session,
    document: LegalDocument | None,
) -> str | None:
    if document is None:
        return None

    chunks = chunk_repository.list_chunks_by_document(db, document.id)
    if not chunks:
        return "chunk_missing"
    for chunk in chunks:
        metadata = chunk.metadata_json or {}
        if metadata.get("chunking_schema_version") != CHUNKING_SCHEMA_VERSION:
            return "chunking_schema_changed"
    return None


def _remove_existing_documents_for_reindex(
    db: Session,
    *,
    metadata: LawOpenApiDocumentMetadata,
    reason: str | None,
) -> list[int]:
    """재색인 대상 문서를 검색 후보에서 제거합니다.

    과거 retrieval 이력이 없는 문서는 실제 삭제하고, 이력이 있는 문서는 FK 감사 추적을
    보존하기 위해 `replaced` 상태로 전환합니다. 두 경우 모두 새 ingestion의 중복/충돌
    판정에서는 제외됩니다.
    """
    documents = document_repository.list_documents_by_identity(
        db,
        document_type=metadata.document_type,
        canonical_id=metadata.canonical_id,
        version_label=metadata.version_label,
        effective_date=metadata.effective_date,
        published_date=metadata.published_date,
    )
    removed_document_ids: list[int] = []
    for document in documents:
        if document.index_status == "replaced":
            continue
        removed_document_ids.append(document.id)
        if document_repository.document_has_retrieval_history(db, document.id):
            document.index_status = "replaced"
            document.index_error = reason or "reindexed"
            document.indexed_at = None
        else:
            document_repository.delete_legal_document(db, document)
    db.flush()
    return removed_document_ids


def _mark_document_indexed(document: LegalDocument) -> None:
    document.index_status = "indexed"
    document.indexed_at = datetime.now(timezone.utc)
    document.index_error = None


def _mark_document_index_failed(
    document: LegalDocument,
    embedding_result: EmbedDocumentChunksResult,
) -> None:
    document.index_status = "failed"
    document.indexed_at = None
    document.index_error = _summarize_embedding_failure(embedding_result)


def _summarize_embedding_failure(result: EmbedDocumentChunksResult) -> str:
    if result.skipped_reason:
        return result.skipped_reason
    if result.failed_count:
        return f"embedding failed for {result.failed_count} chunk(s)"
    if result.skipped_failed_count:
        return f"embedding has {result.skipped_failed_count} failed chunk row(s)"
    return "embedding did not complete for every chunk"


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
