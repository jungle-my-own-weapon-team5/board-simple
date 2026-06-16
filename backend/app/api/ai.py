"""AI Agent 실행 API 라우터입니다."""

from __future__ import annotations

from collections import deque
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.ai import (
    AgentRunCreate,
    AgentRunRead,
    AnswerDraftCreate,
    AnswerDraftRead,
    DisputeIssuesCreate,
    DisputeIssuesRead,
)
from app.services.agent.orchestrator import OrchestratorAgent
from app.services.agent.state import AgentRunRequest, AgentRunResult

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
