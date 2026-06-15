"""RAG chunk를 embedding profile 기준으로 임베딩해 저장하는 서비스입니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.document_chunk import LegalDocumentChunk
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding
from app.repositories import document_chunks as chunk_repository
from app.repositories import embeddings as embedding_repository
from app.repositories import legal_documents as document_repository
from app.services.ai.errors import ProviderError
from app.services.ai.types import EmbeddingRequest, EmbeddingResult
from app.services.rag.normalization import calculate_text_checksum


class EmbeddingClient(Protocol):
    """AIClient 또는 테스트용 fake client가 만족해야 하는 최소 계약입니다."""

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        """여러 text를 provider embedding 결과로 변환합니다."""


class EmbeddingResponseValidationError(ValueError):
    """provider 응답이 선택한 embedding profile 계약과 맞지 않는 경우입니다."""


@dataclass(frozen=True)
class EmbedDocumentChunksResult:
    """문서 chunk embedding 실행 결과입니다.

    skipped_reason이 있으면 문서 단위로 embedding을 실행하지 않은 것입니다.
    """

    document_id: int
    embedding_profile_id: int
    requested_count: int
    embedded_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    already_embedded_count: int = 0
    skipped_failed_count: int = 0
    stale_count: int = 0
    skipped_reason: str | None = None
    chunk_embedding_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class _EmbeddingTarget:
    """이번 실행에서 provider 호출 대상이 되는 chunk/embedding row 묶음입니다."""

    chunk: LegalDocumentChunk
    chunk_embedding: LegalDocumentChunkEmbedding
    content_checksum: str


def embed_document_chunks(
    db: Session,
    *,
    document_id: int,
    embedding_profile: EmbeddingProfile,
    ai_client: EmbeddingClient,
    timeout_seconds: int = 60,
    batch_size: int = 16,
    retry_failed: bool = False,
    force_reembed: bool = False,
    commit: bool = True,
) -> EmbedDocumentChunksResult:
    """문서에 속한 chunk들을 선택한 embedding profile로 임베딩합니다.

    service 계층 함수이므로 기본적으로 commit/rollback을 담당합니다. batch 작업에서
    여러 문서를 하나의 transaction으로 묶으려면 `commit=False`로 호출합니다.
    """
    try:
        result = _embed_document_chunks_without_commit(
            db,
            document_id=document_id,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            timeout_seconds=timeout_seconds,
            batch_size=batch_size,
            retry_failed=retry_failed,
            force_reembed=force_reembed,
        )
        if commit:
            db.commit()
            for chunk_embedding_id in result.chunk_embedding_ids:
                chunk_embedding = embedding_repository.get_chunk_embedding(
                    db, chunk_embedding_id
                )
                if chunk_embedding is not None:
                    db.refresh(chunk_embedding)
        return result
    except Exception:
        if commit:
            db.rollback()
        raise


def _embed_document_chunks_without_commit(
    db: Session,
    *,
    document_id: int,
    embedding_profile: EmbeddingProfile,
    ai_client: EmbeddingClient,
    timeout_seconds: int,
    batch_size: int,
    retry_failed: bool,
    force_reembed: bool,
) -> EmbedDocumentChunksResult:
    _validate_embedding_profile(embedding_profile)
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    document = document_repository.get_legal_document(db, document_id)
    if document is None:
        raise ValueError("legal document not found")

    chunks = chunk_repository.list_chunks_by_document(db, document_id)
    skipped_reason = _get_document_skip_reason(document.dedup_status, document.conflict_status)
    if skipped_reason is not None:
        return EmbedDocumentChunksResult(
            document_id=document_id,
            embedding_profile_id=embedding_profile.id,
            requested_count=len(chunks),
            skipped_count=len(chunks),
            skipped_reason=skipped_reason,
        )

    targets: list[_EmbeddingTarget] = []
    already_embedded_count = 0
    skipped_failed_count = 0
    stale_count = 0

    for chunk in chunks:
        content_checksum = calculate_text_checksum(chunk.content)
        chunk_embedding = _get_or_create_chunk_embedding(
            db,
            chunk_id=chunk.id,
            embedding_profile_id=embedding_profile.id,
            content_checksum=content_checksum,
        )

        # 같은 content/profile로 이미 성공한 row는 중복 provider 호출을 하지 않습니다.
        if (
            chunk_embedding.embedding_status == "embedded"
            and chunk_embedding.content_checksum == content_checksum
            and not force_reembed
        ):
            already_embedded_count += 1
            continue

        # 실패 row는 명시적인 retry 요청이 있을 때만 다시 provider에 보냅니다.
        if (
            chunk_embedding.embedding_status == "failed"
            and chunk_embedding.content_checksum == content_checksum
            and not retry_failed
            and not force_reembed
        ):
            skipped_failed_count += 1
            continue

        if chunk_embedding.content_checksum != content_checksum:
            stale_count += 1

        # provider 호출 전에는 현재 content 기준으로 pending 상태를 명확히 표시합니다.
        _mark_pending(chunk_embedding, content_checksum)
        targets.append(
            _EmbeddingTarget(
                chunk=chunk,
                chunk_embedding=chunk_embedding,
                content_checksum=content_checksum,
            )
        )

    embedded_count = 0
    failed_count = 0
    for batch_start in range(0, len(targets), batch_size):
        batch = targets[batch_start : batch_start + batch_size]
        batch_result = _embed_target_batch(
            batch,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            timeout_seconds=timeout_seconds,
        )
        embedded_count += batch_result.embedded_count
        failed_count += batch_result.failed_count

    chunk_embedding_ids = [
        target.chunk_embedding.id
        for target in targets
        if target.chunk_embedding.id is not None
    ]
    return EmbedDocumentChunksResult(
        document_id=document_id,
        embedding_profile_id=embedding_profile.id,
        requested_count=len(chunks),
        embedded_count=embedded_count,
        failed_count=failed_count,
        skipped_count=already_embedded_count + skipped_failed_count,
        already_embedded_count=already_embedded_count,
        skipped_failed_count=skipped_failed_count,
        stale_count=stale_count,
        chunk_embedding_ids=chunk_embedding_ids,
    )


@dataclass(frozen=True)
class _BatchEmbeddingResult:
    embedded_count: int
    failed_count: int


def _embed_target_batch(
    targets: list[_EmbeddingTarget],
    *,
    embedding_profile: EmbeddingProfile,
    ai_client: EmbeddingClient,
    timeout_seconds: int,
) -> _BatchEmbeddingResult:
    if not targets:
        return _BatchEmbeddingResult(embedded_count=0, failed_count=0)

    request = EmbeddingRequest(
        texts=[target.chunk.content for target in targets],
        model=embedding_profile.model_name,
        dimensions=embedding_profile.dimensions,
        timeout_seconds=timeout_seconds,
        metadata={
            "embedding_profile_id": str(embedding_profile.id),
            "provider": embedding_profile.provider,
        },
    )

    try:
        provider_results = ai_client.embed_texts(request)
        ordered_results = _validate_provider_results(
            provider_results,
            expected_count=len(targets),
            embedding_profile=embedding_profile,
        )
    except (ProviderError, EmbeddingResponseValidationError) as exc:
        # provider 오류나 응답 계약 위반은 chunk/document를 손상시키지 않고 row 상태로 남깁니다.
        safe_error = _sanitize_embedding_error(exc)
        for target in targets:
            _mark_failed(target.chunk_embedding, target.content_checksum, safe_error)
        return _BatchEmbeddingResult(embedded_count=0, failed_count=len(targets))

    now = datetime.now(timezone.utc)
    for target, provider_result in zip(targets, ordered_results, strict=True):
        target.chunk_embedding.embedding = provider_result.embedding
        target.chunk_embedding.embedding_status = "embedded"
        target.chunk_embedding.embedded_at = now
        target.chunk_embedding.embedding_error = None
        target.chunk_embedding.content_checksum = target.content_checksum
        target.chunk_embedding.metadata_json = {
            **(target.chunk_embedding.metadata_json or {}),
            "embedding_provider": provider_result.embedding_provider,
            "embedding_model_name": provider_result.embedding_model_name,
            "embedding_dimensions": provider_result.dimensions,
        }

    return _BatchEmbeddingResult(embedded_count=len(targets), failed_count=0)


def _validate_embedding_profile(embedding_profile: EmbeddingProfile) -> None:
    if embedding_profile.id is None:
        raise ValueError("embedding_profile must be persisted before embedding")
    if not embedding_profile.provider.strip():
        raise ValueError("embedding_profile.provider must not be blank")
    if not embedding_profile.model_name.strip():
        raise ValueError("embedding_profile.model_name must not be blank")
    if embedding_profile.dimensions <= 0:
        raise ValueError("embedding_profile.dimensions must be positive")
    if embedding_profile.status != "active":
        raise ValueError("embedding_profile must be active")


def _get_document_skip_reason(
    dedup_status: str,
    conflict_status: str,
) -> str | None:
    if dedup_status == "duplicate":
        return "duplicate_document"
    if conflict_status != "none":
        return "document_conflict"
    return None


def _get_or_create_chunk_embedding(
    db: Session,
    *,
    chunk_id: int,
    embedding_profile_id: int,
    content_checksum: str,
) -> LegalDocumentChunkEmbedding:
    chunk_embedding = embedding_repository.find_chunk_embedding(
        db,
        chunk_id=chunk_id,
        embedding_profile_id=embedding_profile_id,
    )
    if chunk_embedding is not None:
        return chunk_embedding

    chunk_embedding = LegalDocumentChunkEmbedding(
        chunk_id=chunk_id,
        embedding_profile_id=embedding_profile_id,
        embedding_status="pending",
        content_checksum=content_checksum,
    )
    embedding_repository.add_chunk_embedding(db, chunk_embedding)
    db.flush()
    return chunk_embedding


def _mark_pending(
    chunk_embedding: LegalDocumentChunkEmbedding,
    content_checksum: str,
) -> None:
    chunk_embedding.embedding = None
    chunk_embedding.embedding_status = "pending"
    chunk_embedding.embedded_at = None
    chunk_embedding.embedding_error = None
    chunk_embedding.content_checksum = content_checksum


def _mark_failed(
    chunk_embedding: LegalDocumentChunkEmbedding,
    content_checksum: str,
    error_message: str,
) -> None:
    chunk_embedding.embedding = None
    chunk_embedding.embedding_status = "failed"
    chunk_embedding.embedded_at = None
    chunk_embedding.embedding_error = error_message
    chunk_embedding.content_checksum = content_checksum


def _validate_provider_results(
    provider_results: list[EmbeddingResult],
    *,
    expected_count: int,
    embedding_profile: EmbeddingProfile,
) -> list[EmbeddingResult]:
    if len(provider_results) != expected_count:
        raise EmbeddingResponseValidationError(
            f"embedding result count mismatch: expected {expected_count}, "
            f"got {len(provider_results)}"
        )

    results_by_index: dict[int, EmbeddingResult] = {}
    for result in provider_results:
        if result.input_index < 0 or result.input_index >= expected_count:
            raise EmbeddingResponseValidationError("embedding result index out of range")
        if result.input_index in results_by_index:
            raise EmbeddingResponseValidationError("embedding result index duplicated")
        if result.embedding_provider != embedding_profile.provider:
            raise EmbeddingResponseValidationError("embedding provider mismatch")
        if result.embedding_model_name != embedding_profile.model_name:
            raise EmbeddingResponseValidationError("embedding model mismatch")
        if result.dimensions != embedding_profile.dimensions:
            raise EmbeddingResponseValidationError("embedding dimensions mismatch")
        if len(result.embedding) != embedding_profile.dimensions:
            raise EmbeddingResponseValidationError("embedding vector length mismatch")
        results_by_index[result.input_index] = result

    missing_indexes = set(range(expected_count)) - set(results_by_index)
    if missing_indexes:
        raise EmbeddingResponseValidationError("embedding result index missing")

    return [results_by_index[index] for index in range(expected_count)]


def _sanitize_embedding_error(exc: Exception) -> str:
    # provider 원본 오류가 너무 길거나 줄바꿈을 포함해도 DB에는 짧은 단일 문자열만 남깁니다.
    message = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if not message:
        message = exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"[:500]
