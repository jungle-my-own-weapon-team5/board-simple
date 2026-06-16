"""RAG 검색 API 라우터입니다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.embedding import EmbeddingProfile
from app.models.user import User
from app.repositories import embeddings as embedding_repository
from app.schemas.rag import RagSearchCreate, RagSearchRead
from app.services.ai.client import AIClient
from app.services.rag.embedding_profiles import (
    EmbeddingProfileConfigError,
    get_active_or_create_default_embedding_profile,
)
from app.services.rag.legal_open_api import LawOpenApiClient
from app.services.rag.legal_open_api_sync import sync_and_embed_law_open_api_statute
from app.services.rag.retrieval import search_legal_documents

router = APIRouter(prefix="/rag", tags=["rag"])

PROVIDER_ERROR_CODES = {
    "ProviderAuthError",
    "ProviderCapabilityError",
    "ProviderConfigError",
    "ProviderRateLimitError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
}
INTERNAL_SEARCH_ERROR_CODES = {"RetrievalResponseValidationError"}


@router.post("/search", response_model=RagSearchRead)
def search_rag_documents(
    payload: RagSearchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> RagSearchRead:
    """답변 생성 없이 관련 법률 chunk만 검색합니다."""

    _ensure_ai_rag_enabled(settings)
    embedding_profile = _select_embedding_profile(
        db,
        settings=settings,
        embedding_profile_id=payload.embedding_profile_id,
    )
    ai_client = AIClient(settings)
    result = search_legal_documents(
        db,
        user_id=current_user.id,
        query=payload.query,
        embedding_profile=embedding_profile,
        ai_client=ai_client,
        search_mode=payload.search_mode,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
        max_chunks_per_document=payload.max_chunks_per_document,
        prompt_version=settings.rag_prompt_version,
        timeout_seconds=settings.ai_request_timeout_seconds,
        document_types=_document_types_from_filters(payload),
    )
    if result.status == "failed":
        _raise_search_failure(result.error_code, result.error_message)
    if not result.results and _should_try_official_source_sync(settings, payload):
        sync_result = sync_and_embed_law_open_api_statute(
            db,
            client=LawOpenApiClient(
                oc=settings.law_open_api_oc,
                base_url=settings.law_open_api_base_url,
                service_url=settings.law_open_api_service_url,
                timeout_seconds=settings.mcp_request_timeout_seconds,
            ),
            query=payload.query,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            search_limit=1,
            timeout_seconds=settings.ai_request_timeout_seconds,
        )
        if sync_result.status in {"embedded", "reused"}:
            result = search_legal_documents(
                db,
                user_id=current_user.id,
                query=payload.query,
                embedding_profile=embedding_profile,
                ai_client=ai_client,
                search_mode=payload.search_mode,
                top_k=payload.top_k,
                score_threshold=payload.score_threshold,
                max_chunks_per_document=payload.max_chunks_per_document,
                prompt_version=settings.rag_prompt_version,
                timeout_seconds=settings.ai_request_timeout_seconds,
                document_types=_document_types_from_filters(payload),
            )
            if result.status == "failed":
                _raise_search_failure(result.error_code, result.error_message)
    return RagSearchRead.from_service_result(result)


def _ensure_ai_rag_enabled(settings: Settings) -> None:
    if settings.ai_rag_enabled:
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="AI/RAG API is disabled",
    )


def _select_embedding_profile(
    db: Session,
    *,
    settings: Settings,
    embedding_profile_id: int | None,
) -> EmbeddingProfile:
    if embedding_profile_id is not None:
        profile = embedding_repository.get_embedding_profile(db, embedding_profile_id)
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Embedding profile was not found",
            )
        return profile

    try:
        return get_active_or_create_default_embedding_profile(db, settings)
    except EmbeddingProfileConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


def _document_types_from_filters(payload: RagSearchCreate) -> list[str] | None:
    filters = payload.filters
    if filters is None:
        return None
    if filters.document_type is not None:
        return [filters.document_type]
    if filters.document_types is not None:
        return list(filters.document_types)
    return None


def _should_try_official_source_sync(
    settings: Settings,
    payload: RagSearchCreate,
) -> bool:
    if not settings.law_open_api_oc.strip():
        return False
    document_types = _document_types_from_filters(payload)
    return document_types is None or "statute" in document_types


def _raise_search_failure(
    error_code: str | None,
    error_message: str | None,
) -> None:
    safe_error_code = error_code or "rag_search_failed"
    raise HTTPException(
        status_code=_status_code_for_search_error(safe_error_code),
        detail={
            "error_code": safe_error_code,
            "message": _public_error_message(safe_error_code, error_message),
        },
    )


def _status_code_for_search_error(error_code: str) -> int:
    if error_code in {
        "ProviderRateLimitError",
        "ProviderTimeoutError",
        "ProviderUnavailableError",
    }:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error_code == "ProviderConfigError":
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    if error_code in PROVIDER_ERROR_CODES:
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_502_BAD_GATEWAY


def _public_error_message(error_code: str, error_message: str | None) -> str:
    # Provider 오류는 외부 응답 원문이나 설정값을 포함할 수 있어 공개 메시지로 재사용하지 않습니다.
    if error_code in PROVIDER_ERROR_CODES or error_code in INTERNAL_SEARCH_ERROR_CODES:
        return error_code
    return error_message or "RAG search failed"
