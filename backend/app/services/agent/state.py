"""단일 Orchestrator Agent의 입력, 출력, 상태 타입입니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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

