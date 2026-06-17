"""Supervisor 기반 멀티에이전트 workflow의 공통 계약입니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.services.agent.state import AgentRunRequest, AgentToolCallSummary
from app.services.ai.types import AITextResult


AgentName = Literal[
    "domain_planner",
    "criminal_law",
    "civil_law",
    "labor_law",
    "administrative_law",
    "lease_law",
    "evidence_verifier",
    "synthesis",
    "issue_spotting",
    "retrieval",
    "legal_source",
    "drafting",
    "citation_verifier",
    "safety_review",
]
AgentResultStatus = Literal["completed", "failed"]


@dataclass(frozen=True)
class AgentTask:
    """Supervisor가 전문 Agent 하나에게 넘기는 단일 작업 단위입니다."""

    agent_name: AgentName
    input: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentHandoff:
    """전문 Agent가 다음 Agent 실행을 Supervisor에게 요청하는 결과입니다."""

    next_agent: AgentName
    reason: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    """전문 Agent 실행 결과와 다음 handoff 요청입니다."""

    agent_name: AgentName
    status: AgentResultStatus
    output: dict[str, object] = field(default_factory=dict)
    handoff: AgentHandoff | None = None
    confidence: float | None = None
    requires_human_review: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class AgentContext:
    """Supervisor가 전문 Agent 사이에 전달하는 공유 상태입니다."""

    request: AgentRunRequest
    issue_plan: dict[str, object] = field(default_factory=dict)
    domain_tasks: list[dict[str, object]] = field(default_factory=list)
    domain_reports: list[dict[str, object]] = field(default_factory=list)
    verified_evidence: list[dict[str, object]] = field(default_factory=list)
    synthesis_report: dict[str, object] = field(default_factory=dict)
    rag_run_id: int | None = None
    evidence_items: list[dict[str, object]] = field(default_factory=list)
    citations: list[dict[str, object]] = field(default_factory=list)
    draft_result: AITextResult | None = None
    answer: str | None = None
    tool_calls: list[AgentToolCallSummary] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class SpecializedAgent(Protocol):
    """Supervisor가 호출할 수 있는 전문 Agent 인터페이스입니다."""

    agent_name: AgentName

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        """전문 Agent 작업을 수행하고 결과 또는 handoff를 반환합니다."""
