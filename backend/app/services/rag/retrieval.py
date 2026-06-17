"""RAG vector retrieval 코어 서비스입니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.models.embedding import EmbeddingProfile
from app.models.rag_run import RagRetrieval, RagRun
from app.repositories import embeddings as embedding_repository
from app.repositories.embeddings import ChunkEmbeddingSearchResult
from app.repositories import rag_runs as rag_run_repository
from app.services.ai.errors import ProviderError
from app.services.ai.types import EmbeddingRequest, EmbeddingResult
from app.services.rag.chunking import (
    has_article_boundary_contamination,
    is_title_only_article_chunk,
)
from app.services.rag.normalization import calculate_text_checksum


RetrievalSearchMode = Literal["focused_answer", "issue_spotting"]
DEFAULT_FOCUSED_ANSWER_TOP_K = 8
DEFAULT_ISSUE_SPOTTING_TOP_K = 50


class RetrievalEmbeddingClient(Protocol):
    """AIClient 또는 테스트용 fake client가 만족해야 하는 최소 계약입니다."""

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        """검색 query를 provider embedding 결과로 변환합니다."""


class RetrievalResponseValidationError(ValueError):
    """query embedding provider 응답이 선택한 profile 계약과 맞지 않는 경우입니다."""


@dataclass(frozen=True)
class RagSearchResultItem:
    """사용자에게 반환하거나 MCP tool이 재사용할 검색 결과 1건입니다."""

    retrieval_id: int | None
    chunk_embedding_id: int
    chunk_id: int
    document_id: int
    rank: int
    score: float
    title: str
    source_url: str | None
    heading: str | None
    content: str
    metadata_json: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchLegalDocumentsResult:
    """검색 실행 결과와 감사 추적용 run metadata입니다."""

    run_id: int
    user_id: int
    query: str
    search_mode: RetrievalSearchMode
    top_k: int
    score_threshold: float | None
    max_chunks_per_document: int | None
    status: str
    embedding_profile_id: int
    embedding_provider: str
    embedding_model_name: str
    embedding_dimensions: int
    prompt_version: str
    results: list[RagSearchResultItem] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


def search_legal_documents(
    db: Session,
    *,
    user_id: int,
    query: str,
    embedding_profile: EmbeddingProfile,
    ai_client: RetrievalEmbeddingClient,
    search_mode: RetrievalSearchMode = "focused_answer",
    top_k: int | None = None,
    score_threshold: float | None = None,
    max_chunks_per_document: int | None = None,
    prompt_version: str = "v1",
    timeout_seconds: int = 60,
    document_types: list[str] | None = None,
    commit: bool = True,
) -> SearchLegalDocumentsResult:
    """query와 관련 있는 법률 문서 chunk를 vector similarity로 검색합니다.

    service 계층 함수이므로 기본적으로 commit/rollback을 담당합니다. API, MCP tool,
    Agent가 모두 같은 검색 코어를 재사용할 수 있도록 HTTP 응답 형식에는 의존하지 않습니다.
    """
    try:
        result = _search_legal_documents_without_commit(
            db,
            user_id=user_id,
            query=query,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            search_mode=search_mode,
            top_k=top_k,
            score_threshold=score_threshold,
            max_chunks_per_document=max_chunks_per_document,
            prompt_version=prompt_version,
            timeout_seconds=timeout_seconds,
            document_types=document_types,
        )
        if commit:
            db.commit()
        return result
    except Exception:
        if commit:
            db.rollback()
        raise


def _search_legal_documents_without_commit(
    db: Session,
    *,
    user_id: int,
    query: str,
    embedding_profile: EmbeddingProfile,
    ai_client: RetrievalEmbeddingClient,
    search_mode: RetrievalSearchMode,
    top_k: int | None,
    score_threshold: float | None,
    max_chunks_per_document: int | None,
    prompt_version: str,
    timeout_seconds: int,
    document_types: list[str] | None,
) -> SearchLegalDocumentsResult:
    search_options = _resolve_search_options(
        search_mode=search_mode,
        top_k=top_k,
        score_threshold=score_threshold,
        max_chunks_per_document=max_chunks_per_document,
    )
    normalized_query = _validate_search_input(
        query=query,
        top_k=search_options.top_k,
        score_threshold=search_options.score_threshold,
        max_chunks_per_document=search_options.max_chunks_per_document,
        timeout_seconds=timeout_seconds,
        embedding_profile=embedding_profile,
    )
    normalized_document_types = _normalize_document_types(document_types)
    rag_run = _create_pending_search_run(
        user_id=user_id,
        query=normalized_query,
        embedding_profile=embedding_profile,
        prompt_version=prompt_version,
    )
    rag_run_repository.add_rag_run(db, rag_run)
    db.flush()

    query_embedding_result = _embed_query(
        ai_client=ai_client,
        query=normalized_query,
        embedding_profile=embedding_profile,
        timeout_seconds=timeout_seconds,
    )
    if query_embedding_result.status == "failed":
        _mark_rag_run_failed(
            rag_run,
            error_code=query_embedding_result.error_code,
            error_message=query_embedding_result.error_message,
        )
        db.flush()
        return _build_failed_result(
            rag_run,
            embedding_profile=embedding_profile,
            search_mode=search_options.search_mode,
            top_k=search_options.top_k,
            score_threshold=search_options.score_threshold,
            max_chunks_per_document=search_options.max_chunks_per_document,
            prompt_version=prompt_version,
        )

    scored_candidates = embedding_repository.search_similar_chunk_embeddings(
        db,
        embedding_profile_id=embedding_profile.id,
        query_vector=query_embedding_result.embedding,
        top_k=_search_candidate_limit(
            search_options.top_k,
            search_mode=search_options.search_mode,
            max_chunks_per_document=search_options.max_chunks_per_document,
        ),
        expected_dimensions=embedding_profile.dimensions,
        document_types=normalized_document_types,
    )
    selected_candidates = _filter_current_search_results(
        scored_candidates,
        top_k=search_options.top_k,
        score_threshold=search_options.score_threshold,
        max_chunks_per_document=search_options.max_chunks_per_document,
    )
    result_items = _persist_retrievals(
        db,
        rag_run=rag_run,
        selected_candidates=selected_candidates,
    )

    rag_run.status = "completed"
    rag_run.error_code = None
    rag_run.error_message = None
    db.flush()

    return SearchLegalDocumentsResult(
        run_id=rag_run.id,
        user_id=user_id,
        query=normalized_query,
        search_mode=search_options.search_mode,
        top_k=search_options.top_k,
        score_threshold=search_options.score_threshold,
        max_chunks_per_document=search_options.max_chunks_per_document,
        status=rag_run.status,
        embedding_profile_id=embedding_profile.id,
        embedding_provider=embedding_profile.provider,
        embedding_model_name=embedding_profile.model_name,
        embedding_dimensions=embedding_profile.dimensions,
        prompt_version=prompt_version,
        results=result_items,
    )


@dataclass(frozen=True)
class _QueryEmbeddingResult:
    status: str
    embedding: list[float] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class _ResolvedSearchOptions:
    """검색 목적에 따라 결정된 최종 retrieval 파라미터입니다."""

    search_mode: RetrievalSearchMode
    top_k: int
    score_threshold: float | None
    max_chunks_per_document: int | None


def _embed_query(
    *,
    ai_client: RetrievalEmbeddingClient,
    query: str,
    embedding_profile: EmbeddingProfile,
    timeout_seconds: int,
) -> _QueryEmbeddingResult:
    request = EmbeddingRequest(
        texts=[query],
        model=embedding_profile.model_name,
        dimensions=embedding_profile.dimensions,
        timeout_seconds=timeout_seconds,
        metadata={
            "embedding_profile_id": str(embedding_profile.id),
            "provider": embedding_profile.provider,
            "purpose": "retrieval_query",
        },
    )
    try:
        provider_results = ai_client.embed_texts(request)
        query_embedding = _validate_query_embedding_result(
            provider_results,
            embedding_profile=embedding_profile,
        )
    except (ProviderError, RetrievalResponseValidationError) as exc:
        # 검색 실패도 rag_runs에 남기되, provider 원문 오류는 짧게 정제해서 저장합니다.
        return _QueryEmbeddingResult(
            status="failed",
            error_code=exc.__class__.__name__,
            error_message=_sanitize_retrieval_error(exc),
        )

    return _QueryEmbeddingResult(status="embedded", embedding=query_embedding)


def _resolve_search_options(
    *,
    search_mode: RetrievalSearchMode,
    top_k: int | None,
    score_threshold: float | None,
    max_chunks_per_document: int | None,
) -> _ResolvedSearchOptions:
    if search_mode == "focused_answer":
        resolved_top_k = top_k if top_k is not None else DEFAULT_FOCUSED_ANSWER_TOP_K
    elif search_mode == "issue_spotting":
        # 쟁점 탐지에서는 한 문서 안의 여러 조문/구성요건이 모두 필요할 수 있으므로
        # 기본 검색 예산을 넓게 잡고 문서별 chunk 제한은 호출자가 명시할 때만 적용합니다.
        resolved_top_k = top_k if top_k is not None else DEFAULT_ISSUE_SPOTTING_TOP_K
    else:
        raise ValueError("search_mode must be focused_answer or issue_spotting")

    return _ResolvedSearchOptions(
        search_mode=search_mode,
        top_k=resolved_top_k,
        score_threshold=score_threshold,
        max_chunks_per_document=max_chunks_per_document,
    )


def _validate_search_input(
    *,
    query: str,
    top_k: int,
    score_threshold: float | None,
    max_chunks_per_document: int | None,
    timeout_seconds: int,
    embedding_profile: EmbeddingProfile,
) -> str:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be blank")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if score_threshold is not None and not 0 <= score_threshold <= 1:
        raise ValueError("score_threshold must be between 0 and 1")
    if max_chunks_per_document is not None and max_chunks_per_document <= 0:
        raise ValueError("max_chunks_per_document must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    _validate_embedding_profile(embedding_profile)
    return normalized_query


def _validate_embedding_profile(embedding_profile: EmbeddingProfile) -> None:
    if embedding_profile.id is None:
        raise ValueError("embedding_profile must be persisted before retrieval")
    if not embedding_profile.provider.strip():
        raise ValueError("embedding_profile.provider must not be blank")
    if not embedding_profile.model_name.strip():
        raise ValueError("embedding_profile.model_name must not be blank")
    if embedding_profile.dimensions <= 0:
        raise ValueError("embedding_profile.dimensions must be positive")
    if embedding_profile.status != "active":
        raise ValueError("embedding_profile must be active")
    if embedding_profile.distance_metric != "cosine":
        raise ValueError("only cosine embedding profile retrieval is supported")


def _normalize_document_types(document_types: list[str] | None) -> list[str] | None:
    if document_types is None:
        return None
    normalized_types = [
        document_type.strip().lower()
        for document_type in document_types
        if document_type.strip()
    ]
    return normalized_types or None


def _create_pending_search_run(
    *,
    user_id: int,
    query: str,
    embedding_profile: EmbeddingProfile,
    prompt_version: str,
) -> RagRun:
    return RagRun(
        user_id=user_id,
        run_type="search",
        query=query,
        facts=None,
        status="pending",
        answer=None,
        disclaimer=None,
        agent_provider=None,
        agent_model_name=None,
        embedding_profile_id=embedding_profile.id,
        embedding_provider=embedding_profile.provider,
        embedding_model_name=embedding_profile.model_name,
        embedding_dimensions=embedding_profile.dimensions,
        prompt_version=prompt_version,
    )


def _validate_query_embedding_result(
    provider_results: list[EmbeddingResult],
    *,
    embedding_profile: EmbeddingProfile,
) -> list[float]:
    if len(provider_results) != 1:
        raise RetrievalResponseValidationError("query embedding result count mismatch")

    result = provider_results[0]
    if result.input_index != 0:
        raise RetrievalResponseValidationError("query embedding result index mismatch")
    if result.embedding_provider != embedding_profile.provider:
        raise RetrievalResponseValidationError("query embedding provider mismatch")
    if result.embedding_model_name != embedding_profile.model_name:
        raise RetrievalResponseValidationError("query embedding model mismatch")
    if result.dimensions != embedding_profile.dimensions:
        raise RetrievalResponseValidationError("query embedding dimensions mismatch")
    if len(result.embedding) != embedding_profile.dimensions:
        raise RetrievalResponseValidationError("query embedding vector length mismatch")
    return result.embedding


def _search_candidate_limit(
    top_k: int,
    *,
    search_mode: RetrievalSearchMode,
    max_chunks_per_document: int | None,
) -> int:
    """후처리 필터로 top_k가 부족해지는 상황을 줄이기 위한 후보 개수입니다."""

    base_limit = max(top_k * 5, top_k + 20)
    if search_mode == "issue_spotting":
        return max(base_limit, top_k * 10, top_k + 200)
    if max_chunks_per_document is None:
        return base_limit
    # 문서별 개수 제한을 걸면 상위 후보가 같은 문서에 몰릴 수 있어 더 넉넉히 가져옵니다.
    return max(base_limit, top_k * 20, top_k + 100)


def _filter_current_search_results(
    scored_candidates: list[ChunkEmbeddingSearchResult],
    *,
    top_k: int,
    score_threshold: float | None,
    max_chunks_per_document: int | None,
) -> list[ChunkEmbeddingSearchResult]:
    filtered_candidates: list[ChunkEmbeddingSearchResult] = []
    selected_count_by_document: dict[int, int] = {}
    for scored_candidate in scored_candidates:
        chunk_embedding = scored_candidate.chunk_embedding
        if chunk_embedding.content_checksum != calculate_text_checksum(
            chunk_embedding.chunk.content
        ):
            continue
        if is_title_only_article_chunk(
            heading=chunk_embedding.chunk.heading,
            content=chunk_embedding.chunk.content,
        ):
            continue
        if has_article_boundary_contamination(
            heading=chunk_embedding.chunk.heading,
            content=chunk_embedding.chunk.content,
        ):
            continue
        if score_threshold is not None and scored_candidate.score < score_threshold:
            continue

        document_id = chunk_embedding.chunk.document_id
        selected_count = selected_count_by_document.get(document_id, 0)
        if (
            max_chunks_per_document is not None
            and selected_count >= max_chunks_per_document
        ):
            continue

        filtered_candidates.append(scored_candidate)
        selected_count_by_document[document_id] = selected_count + 1
        if len(filtered_candidates) == top_k:
            break
    return filtered_candidates


def _persist_retrievals(
    db: Session,
    *,
    rag_run: RagRun,
    selected_candidates: list[ChunkEmbeddingSearchResult],
) -> list[RagSearchResultItem]:
    result_items: list[RagSearchResultItem] = []
    retrieval_rows: list[RagRetrieval] = []

    for index, scored_candidate in enumerate(selected_candidates, start=1):
        chunk_embedding = scored_candidate.chunk_embedding
        chunk = chunk_embedding.chunk
        document = chunk.document
        retrieval = RagRetrieval(
            rag_run_id=rag_run.id,
            chunk_id=chunk.id,
            chunk_embedding_id=chunk_embedding.id,
            embedding_profile_id=chunk_embedding.embedding_profile_id,
            rank=index,
            score=scored_candidate.score,
            retrieval_type="vector",
        )
        rag_run_repository.add_rag_retrieval(db, retrieval)
        retrieval_rows.append(retrieval)
        result_items.append(
            RagSearchResultItem(
                retrieval_id=None,
                chunk_embedding_id=chunk_embedding.id,
                chunk_id=chunk.id,
                document_id=document.id,
                rank=index,
                score=scored_candidate.score,
                title=document.title,
                source_url=document.source.source_url if document.source else None,
                heading=chunk.heading,
                content=chunk.content,
                metadata_json={
                    **(chunk.metadata_json or {}),
                    "document_type": document.document_type,
                    "canonical_id": document.canonical_id,
                    "version_label": document.version_label,
                },
            )
        )

    db.flush()
    return [
        RagSearchResultItem(
            **{
                **result_item.__dict__,
                "retrieval_id": retrieval.id,
            }
        )
        for result_item, retrieval in zip(result_items, retrieval_rows, strict=True)
    ]


def _mark_rag_run_failed(
    rag_run: RagRun,
    *,
    error_code: str | None,
    error_message: str | None,
) -> None:
    rag_run.status = "failed"
    rag_run.error_code = error_code
    rag_run.error_message = error_message


def _build_failed_result(
    rag_run: RagRun,
    *,
    embedding_profile: EmbeddingProfile,
    search_mode: RetrievalSearchMode,
    top_k: int,
    score_threshold: float | None,
    max_chunks_per_document: int | None,
    prompt_version: str,
) -> SearchLegalDocumentsResult:
    return SearchLegalDocumentsResult(
        run_id=rag_run.id,
        user_id=rag_run.user_id,
        query=rag_run.query,
        search_mode=search_mode,
        top_k=top_k,
        score_threshold=score_threshold,
        max_chunks_per_document=max_chunks_per_document,
        status=rag_run.status,
        embedding_profile_id=embedding_profile.id,
        embedding_provider=embedding_profile.provider,
        embedding_model_name=embedding_profile.model_name,
        embedding_dimensions=embedding_profile.dimensions,
        prompt_version=prompt_version,
        results=[],
        error_code=rag_run.error_code,
        error_message=rag_run.error_message,
    )


def _sanitize_retrieval_error(exc: Exception) -> str:
    message = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if not message:
        message = exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"[:500]
