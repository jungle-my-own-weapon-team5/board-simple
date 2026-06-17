"""AI Agent 실행 API 라우터입니다."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.repositories import rag_runs as rag_run_repository
from app.schemas.ai import (
    AgentRunCreate,
    AgentRunRead,
    AnswerDraftCreate,
    AnswerDraftRead,
    DisputeIssuesCreate,
    DisputeIssuesRead,
    FullAnalysisCreate,
    FullAnalysisRead,
)
from app.schemas.rag import RagSearchItemRead, RagSearchRead
from app.services.agent.orchestrator import OrchestratorAgent
from app.services.agent.state import AgentRunRequest, AgentRunResult
from app.services.rag.chunking import (
    has_article_boundary_contamination,
    is_title_only_article_chunk,
)
from app.services.rag.retrieval import (
    DEFAULT_FOCUSED_ANSWER_TOP_K,
    DEFAULT_ISSUE_SPOTTING_TOP_K,
)

router = APIRouter(prefix="/ai", tags=["ai"])

PROVIDER_ERROR_CODES = {
    "ProviderAuthError",
    "ProviderCapabilityError",
    "ProviderConfigError",
    "ProviderRateLimitError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
}
AI_RATE_LIMIT_WINDOW_SECONDS = 60
_AI_RATE_LIMIT_LOCK = Lock()
_AI_RATE_LIMIT_BUCKETS: dict[tuple[int, int], deque[float]] = {}


def get_orchestrator_agent(
    settings: Settings = Depends(get_settings),
) -> OrchestratorAgent:
    """라우터가 provider 구현을 직접 알지 않도록 Agent 객체 생성을 분리합니다."""

    return OrchestratorAgent(settings=settings)


@router.post("/agent-runs", response_model=AgentRunRead)
def create_agent_run(
    payload: AgentRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    agent: OrchestratorAgent = Depends(get_orchestrator_agent),
) -> AgentRunRead:
    """공통 Agent 실행 endpoint입니다."""

    _ensure_ai_rag_enabled(settings)
    _enforce_ai_rate_limit(settings, current_user)
    result = _run_agent(
        db,
        agent=agent,
        request=_to_agent_request(current_user.id, payload),
    )
    return AgentRunRead.from_service_result(result)


@router.post("/dispute-issues", response_model=DisputeIssuesRead)
def create_dispute_issues(
    payload: DisputeIssuesCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    agent: OrchestratorAgent = Depends(get_orchestrator_agent),
) -> DisputeIssuesRead:
    """사실관계에서 후보 법률 쟁점을 정리합니다."""

    _ensure_ai_rag_enabled(settings)
    _enforce_ai_rate_limit(settings, current_user)
    result = _run_agent(
        db,
        agent=agent,
        request=AgentRunRequest(
            user_id=current_user.id,
            task_type="dispute_issues",
            facts=payload.facts,
            question=payload.question,
            search_mode=payload.search_mode,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            max_chunks_per_document=payload.max_chunks_per_document,
        ),
    )
    return DisputeIssuesRead.from_service_result(result)


@router.post("/answer-drafts", response_model=AnswerDraftRead)
def create_answer_draft(
    payload: AnswerDraftCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    agent: OrchestratorAgent = Depends(get_orchestrator_agent),
) -> AnswerDraftRead:
    """검색 근거와 citation 검증을 거친 답변 초안을 생성합니다."""

    _ensure_ai_rag_enabled(settings)
    _enforce_ai_rate_limit(settings, current_user)
    result = _run_agent(
        db,
        agent=agent,
        request=AgentRunRequest(
            user_id=current_user.id,
            task_type="answer_draft",
            facts=payload.facts,
            question=payload.question,
            search_mode=payload.search_mode,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            max_chunks_per_document=payload.max_chunks_per_document,
            options=_answer_draft_options(payload),
        ),
    )
    return AnswerDraftRead.from_service_result(result)


@router.post("/full-analysis", response_model=FullAnalysisRead)
def create_full_analysis(
    payload: FullAnalysisCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    agent: OrchestratorAgent = Depends(get_orchestrator_agent),
) -> FullAnalysisRead:
    """검색, 쟁점 정리, 답변 초안을 하나의 Agent 실행으로 생성합니다."""

    _ensure_ai_rag_enabled(settings)
    _enforce_ai_rate_limit(settings, current_user)
    result = _run_agent(
        db,
        agent=agent,
        request=AgentRunRequest(
            user_id=current_user.id,
            task_type="answer_draft",
            facts=payload.facts,
            question=payload.question,
            search_mode=payload.search_mode,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
            max_chunks_per_document=payload.max_chunks_per_document,
            options=_answer_draft_options(payload),
        ),
    )
    issues_text, draft_text = _split_full_analysis_answer(result.answer)
    return FullAnalysisRead(
        search=_rag_search_read_from_run(db, result.run_id, payload),
        issues=DisputeIssuesRead.from_service_result(
            replace(result, task_type="dispute_issues", answer=issues_text)
        ),
        draft=AnswerDraftRead.from_service_result(replace(result, answer=draft_text)),
    )


def _ensure_ai_rag_enabled(settings: Settings) -> None:
    if settings.ai_rag_enabled:
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="AI/RAG API is disabled",
    )


def _enforce_ai_rate_limit(settings: Settings, current_user: User) -> None:
    now = monotonic()
    cutoff = now - AI_RATE_LIMIT_WINDOW_SECONDS
    key = (id(settings), current_user.id)
    with _AI_RATE_LIMIT_LOCK:
        bucket = _AI_RATE_LIMIT_BUCKETS.setdefault(key, deque())
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= settings.ai_rate_limit_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI rate limit exceeded",
            )
        bucket.append(now)


def _run_agent(
    db: Session,
    *,
    agent: OrchestratorAgent,
    request: AgentRunRequest,
) -> AgentRunResult:
    try:
        result = agent.run(db, request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if result.status == "failed":
        _raise_agent_failure(result)
    return result


def _to_agent_request(user_id: int, payload: AgentRunCreate) -> AgentRunRequest:
    return AgentRunRequest(
        user_id=user_id,
        task_type=payload.task_type,
        facts=payload.facts,
        question=payload.question,
        search_mode=payload.search_mode,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
        max_chunks_per_document=payload.max_chunks_per_document,
        options=payload.options,
    )


def _answer_draft_options(payload: AnswerDraftCreate) -> dict[str, object]:
    options: dict[str, object] = {}
    if payload.tone is not None:
        options["tone"] = payload.tone
    return options


def _rag_search_read_from_run(
    db: Session,
    run_id: int,
    payload: FullAnalysisCreate,
) -> RagSearchRead:
    rag_run = rag_run_repository.get_rag_run(db, run_id)
    if rag_run is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent run search result was not found",
        )
    if rag_run.embedding_profile_id is None or rag_run.embedding_dimensions is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent run embedding metadata is missing",
        )

    items: list[RagSearchItemRead] = []
    for retrieval in rag_run_repository.list_retrievals_by_run(db, run_id):
        chunk = retrieval.chunk
        if is_title_only_article_chunk(
            heading=chunk.heading,
            content=chunk.content,
        ) or has_article_boundary_contamination(
            heading=chunk.heading,
            content=chunk.content,
        ):
            continue
        document = chunk.document
        metadata = {
            **(chunk.metadata_json or {}),
            "document_type": document.document_type,
            "canonical_id": document.canonical_id,
            "version_label": document.version_label,
            "retrieval_type": retrieval.retrieval_type,
        }
        if retrieval.chunk_embedding_id is None:
            continue
        items.append(
            RagSearchItemRead(
                retrieval_id=retrieval.id,
                chunk_embedding_id=retrieval.chunk_embedding_id,
                chunk_id=chunk.id,
                document_id=document.id,
                rank=len(items) + 1,
                score=float(retrieval.score or 0),
                title=document.title,
                source_url=document.source.source_url if document.source else None,
                heading=chunk.heading,
                content=chunk.content,
                metadata=metadata,
            )
        )

    return RagSearchRead(
        run_id=rag_run.id,
        query=_combined_query(facts=rag_run.facts or "", question=rag_run.query),
        search_mode=payload.search_mode,
        top_k=_resolved_top_k(payload),
        score_threshold=payload.score_threshold,
        max_chunks_per_document=payload.max_chunks_per_document,
        embedding_profile_id=rag_run.embedding_profile_id,
        embedding_provider=rag_run.embedding_provider,
        embedding_model_name=rag_run.embedding_model_name,
        embedding_dimensions=rag_run.embedding_dimensions,
        items=items,
    )


def _resolved_top_k(payload: FullAnalysisCreate) -> int:
    if payload.top_k is not None:
        return payload.top_k
    if payload.search_mode == "issue_spotting":
        return DEFAULT_ISSUE_SPOTTING_TOP_K
    return DEFAULT_FOCUSED_ANSWER_TOP_K


def _split_full_analysis_answer(answer: str | None) -> tuple[str | None, str | None]:
    if answer is None or not answer.strip():
        return None, None

    lines = answer.splitlines()
    for index, line in enumerate(lines):
        if index == 0:
            continue
        if _is_draft_section_heading(line):
            issues_text = "\n".join(lines[:index]).strip() or answer.strip()
            draft_text = "\n".join(lines[index:]).strip()
            return issues_text, draft_text or answer.strip()
    return answer.strip(), answer.strip()


def _is_draft_section_heading(line: str) -> bool:
    stripped = line.strip()
    while stripped and stripped[0] in "#*-0123456789. )":
        stripped = stripped[1:].strip()
    normalized = "".join(stripped.split())
    return normalized.startswith(("답변초안", "초안방향", "검토의견서초안"))


def _combined_query(*, facts: str, question: str | None) -> str:
    values = [facts.strip(), (question or "").strip()]
    return "\n".join(value for value in values if value)


def _raise_agent_failure(result: AgentRunResult) -> None:
    error_code = result.error_code or "agent_run_failed"
    raise HTTPException(
        status_code=_status_code_for_agent_error(error_code),
        detail={
            "run_id": result.run_id,
            "error_code": error_code,
            "message": _public_error_message(result),
        },
    )


def _status_code_for_agent_error(error_code: str) -> int:
    if error_code == "agent_tool_budget_exceeded":
        return status.HTTP_400_BAD_REQUEST
    if error_code in {"agent_invalid_temperature", "mcp_invalid_arguments"}:
        return status.HTTP_400_BAD_REQUEST
    if error_code in {
        "ProviderConfigError",
        "agent_model_missing",
        "mcp_tool_config_error",
    }:
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    if error_code in {
        "ProviderRateLimitError",
        "ProviderTimeoutError",
        "ProviderUnavailableError",
    }:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error_code in PROVIDER_ERROR_CODES:
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_502_BAD_GATEWAY


def _public_error_message(result: AgentRunResult) -> str:
    error_code = result.error_code or "agent_run_failed"
    # Provider 오류는 외부 응답 원문이나 설정값을 포함할 수 있어 공개 메시지로 재사용하지 않습니다.
    if error_code in PROVIDER_ERROR_CODES:
        return error_code
    if result.error_message:
        return result.error_message
    return "Agent run failed"
