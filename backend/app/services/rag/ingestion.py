"""RAG 문서 수집부터 chunk 생성까지의 1차 ingestion 흐름입니다."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.document_chunk import LegalDocumentChunk
from app.models.legal_document import LegalDocument
from app.models.legal_source import LegalSource
from app.repositories import document_chunks as chunk_repository
from app.repositories import legal_documents as document_repository
from app.services.rag.chunking import ChunkingConfig, chunk_document_text
from app.services.rag.normalization import normalize_document_text


@dataclass(frozen=True)
class IngestLegalDocumentInput:
    """법률 문서 1건을 RAG corpus에 적재하기 위한 입력 값입니다."""

    provider: str
    source_type: str
    document_type: str
    title: str
    raw_text: str
    canonical_id: str | None = None
    version_label: str | None = None
    published_date: date | None = None
    effective_date: date | None = None
    source_url: str | None = None
    external_id: str | None = None
    fetched_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None
    chunking_config: ChunkingConfig | None = None


@dataclass(frozen=True)
class IngestLegalDocumentResult:
    """ingestion 결과와 후속 단계가 참고할 판정 정보를 담습니다."""

    source: LegalSource
    document: LegalDocument
    chunks: list[LegalDocumentChunk]
    duplicate_of_document_id: int | None
    conflicting_document_ids: list[int]

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of_document_id is not None

    @property
    def needs_conflict_review(self) -> bool:
        return bool(self.conflicting_document_ids)


def ingest_legal_document(
    db: Session,
    payload: IngestLegalDocumentInput,
    *,
    commit: bool = True,
) -> IngestLegalDocumentResult:
    """법률 문서를 정규화하고 chunk로 분리해 DB에 저장합니다.

    서비스 계층 함수이므로 기본값으로 transaction을 commit합니다. 여러 문서를
    하나의 transaction으로 묶어야 하는 batch 작업은 `commit=False`로 호출한 뒤
    호출자가 commit/rollback을 제어할 수 있습니다.
    """
    try:
        result = _ingest_legal_document_without_commit(db, payload)
        if commit:
            db.commit()
            db.refresh(result.source)
            db.refresh(result.document)
            for chunk in result.chunks:
                db.refresh(chunk)
        return result
    except Exception:
        if commit:
            db.rollback()
        raise


def _ingest_legal_document_without_commit(
    db: Session, payload: IngestLegalDocumentInput
) -> IngestLegalDocumentResult:
    provider = _normalize_required_label(payload.provider, "provider")
    source_type = _normalize_required_label(payload.source_type, "source_type")
    document_type = _normalize_required_label(payload.document_type, "document_type")
    title = _strip_required_text(payload.title, "title")
    _ensure_not_blank(payload.raw_text, "raw_text")
    raw_text = payload.raw_text

    external_id = _empty_to_none(payload.external_id)
    source = _get_or_create_source(
        db,
        provider=provider,
        source_type=source_type,
        external_id=external_id,
        source_url=_empty_to_none(payload.source_url),
        fetched_at=payload.fetched_at,
        metadata_json=payload.metadata_json or {},
    )

    normalized = normalize_document_text(raw_text)
    canonical_id = _empty_to_none(payload.canonical_id)
    version_label = _empty_to_none(payload.version_label)

    duplicate_candidate = document_repository.find_duplicate_document_candidate(
        db,
        document_type=document_type,
        canonical_id=canonical_id,
        version_label=version_label,
        effective_date=payload.effective_date,
        normalized_checksum=normalized.normalized_checksum,
    )
    conflict_candidates = document_repository.list_conflicting_document_candidates(
        db,
        document_type=document_type,
        canonical_id=canonical_id,
        version_label=version_label,
        effective_date=payload.effective_date,
        normalized_checksum=normalized.normalized_checksum,
    )

    dedup_status = "duplicate" if duplicate_candidate is not None else "unique"
    conflict_status = (
        "review_required"
        if duplicate_candidate is None and conflict_candidates
        else "none"
    )

    document = LegalDocument(
        source_id=source.id,
        document_type=document_type,
        title=title,
        canonical_id=canonical_id,
        version_label=version_label,
        published_date=payload.published_date,
        effective_date=payload.effective_date,
        raw_text=normalized.raw_text,
        normalized_text=normalized.normalized_text,
        raw_checksum=normalized.raw_checksum,
        normalized_checksum=normalized.normalized_checksum,
        dedup_status=dedup_status,
        conflict_status=conflict_status,
        duplicate_of_document_id=(
            duplicate_candidate.id if duplicate_candidate is not None else None
        ),
        index_status="pending",
    )
    document_repository.add_legal_document(db, document)
    db.flush()

    # 중복/충돌 문서도 원문과 chunk를 보존합니다. 후속 retrieval/embedding 단계는
    # document.dedup_status와 conflict_status를 기준으로 색인 제외 여부를 결정합니다.
    chunks = _create_document_chunks(
        db,
        document=document,
        document_type=document_type,
        normalized_text=normalized.normalized_text,
        chunking_config=payload.chunking_config,
    )
    db.flush()

    return IngestLegalDocumentResult(
        source=source,
        document=document,
        chunks=chunks,
        duplicate_of_document_id=document.duplicate_of_document_id,
        conflicting_document_ids=[candidate.id for candidate in conflict_candidates],
    )


def _get_or_create_source(
    db: Session,
    *,
    provider: str,
    source_type: str,
    external_id: str | None,
    source_url: str | None,
    fetched_at: datetime | None,
    metadata_json: dict[str, Any],
) -> LegalSource:
    existing_source = document_repository.find_legal_source_by_provider_external_id(
        db, provider=provider, external_id=external_id
    )
    if existing_source is not None:
        return existing_source

    source = LegalSource(
        provider=provider,
        source_type=source_type,
        external_id=external_id,
        source_url=source_url,
        fetched_at=fetched_at,
        metadata_json=dict(metadata_json),
    )
    document_repository.add_legal_source(db, source)
    db.flush()
    return source


def _create_document_chunks(
    db: Session,
    *,
    document: LegalDocument,
    document_type: str,
    normalized_text: str,
    chunking_config: ChunkingConfig | None,
) -> list[LegalDocumentChunk]:
    text_chunks = chunk_document_text(
        normalized_text,
        document_type=document_type,
        config=chunking_config,
    )
    chunks: list[LegalDocumentChunk] = []
    for text_chunk in text_chunks:
        chunk = LegalDocumentChunk(
            document_id=document.id,
            chunk_index=text_chunk.chunk_index,
            heading=text_chunk.heading,
            content=text_chunk.content,
            token_count=text_chunk.token_count,
            metadata_json={
                **text_chunk.metadata_json,
                "document_type": document.document_type,
                "canonical_id": document.canonical_id,
                "version_label": document.version_label,
                "published_date": _date_to_iso(document.published_date),
                "effective_date": _date_to_iso(document.effective_date),
            },
        )
        chunk_repository.add_document_chunk(db, chunk)
        chunks.append(chunk)
    return chunks


def _normalize_required_label(value: str, field_name: str) -> str:
    stripped_value = _strip_required_text(value, field_name)
    return stripped_value.lower()


def _strip_required_text(value: str, field_name: str) -> str:
    stripped_value = value.strip()
    if not stripped_value:
        raise ValueError(f"{field_name} must not be blank")
    return stripped_value


def _ensure_not_blank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped_value = value.strip()
    return stripped_value or None


def _date_to_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
