"""단일 Orchestrator Agent의 입력, 출력, 상태 타입입니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AgentActionType = Literal[
    "search_internal",
    "search_external_source",
    "sync_official_source",
    "draft_answer",
    "verify_citations",
    "respond_insufficient_evidence",
    "stop",
]
AgentTaskType = Literal["answer_draft", "dispute_issues"]
AgentRunStatus = Literal["completed", "failed"]
AgentSearchMode = Literal["focused_answer", "issue_spotting"]

LEGAL_AI_DISCLAIMER = (
    "이 결과는 법률정보 기반 초안 보조이며 법률 자문이 아닙니다. "
    "중요한 판단 전에는 변호사 등 전문가의 검토가 필요합니다."
)


@dataclass(frozen=True)
class AgentRunRequest:
    user_id: int
    task_type: AgentTaskType
    facts: str
    question: str
    search_mode: AgentSearchMode = "focused_answer"
    top_k: int | None = None
    score_threshold: float | None = None
    max_chunks_per_document: int | None = None
    options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentToolCallSummary:
    step_index: int
    tool_name: str
    status: str


@dataclass(frozen=True)
class AgentAction:
    """LLM 또는 deterministic planner가 제안한 다음 실행 후보입니다."""

    action_type: AgentActionType
    reason: str
    tool_name: str | None = None
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentObservation:
    """Action 실행 결과를 다음 판단에 쓰기 위한 요약입니다."""

    action_type: AgentActionType
    status: str
    summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceAssessment:
    """현재 내부 RAG evidence가 답변 생성에 충분한지에 대한 초기 판단입니다."""

    is_sufficient: bool
    relevant_chunk_count: int
    citation_count: int
    reason: str
    uncovered_issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentRunResult:
    run_id: int
    status: AgentRunStatus
    task_type: AgentTaskType
    agent_provider: str | None
    agent_model_name: str | None
    answer: str | None
    citations: list[dict[str, object]] = field(default_factory=list)
    disclaimer: str | None = LEGAL_AI_DISCLAIMER
    tool_calls: list[AgentToolCallSummary] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None

