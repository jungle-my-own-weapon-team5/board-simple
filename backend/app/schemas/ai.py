"""AI Agent API의 요청/응답 스키마입니다."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.agent.state import AgentRunResult

AgentTaskType = Literal["answer_draft", "dispute_issues"]
AgentRunStatus = Literal["completed", "failed"]
AgentSearchMode = Literal["focused_answer", "issue_spotting"]


class AgentRetrievalOptions(BaseModel):
    """Agent 실행 시 retrieval service로 전달할 검색 옵션입니다."""

    search_mode: AgentSearchMode = "focused_answer"
    top_k: int | None = Field(default=None, ge=1, le=100)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    max_chunks_per_document: int | None = Field(default=None, ge=1, le=100)


class AgentRunCreate(AgentRetrievalOptions):
    """공통 Agent 실행 요청입니다."""

    task_type: AgentTaskType
    facts: str = Field(min_length=1, max_length=20000)
    question: str = Field(min_length=1, max_length=5000)
    # tone, temperature처럼 provider에 직접 전달하지 않는 안전한 실행 옵션만 담습니다.
    options: dict[str, object] = Field(default_factory=dict)


class DisputeIssuesCreate(AgentRetrievalOptions):
    """쟁점 탐지용 편의 endpoint 요청입니다."""

    facts: str = Field(min_length=1, max_length=20000)
    question: str = Field(min_length=1, max_length=5000)
    search_mode: AgentSearchMode = "issue_spotting"


class AnswerDraftCreate(AgentRetrievalOptions):
    """답변 초안용 편의 endpoint 요청입니다."""

    facts: str = Field(min_length=1, max_length=20000)
    question: str = Field(min_length=1, max_length=5000)
    tone: str | None = Field(default=None, min_length=1, max_length=50)


class AgentToolCallRead(BaseModel):
    """사용자에게 노출해도 되는 MCP tool 호출 요약입니다."""

    step_index: int
    tool_name: str
    status: str


class AgentCitationRead(BaseModel):
    """검색 근거를 다시 확인할 수 있는 citation metadata입니다."""

    chunk_id: int | None = None
    title: str | None = None
    source_url: str | None = None
    heading: str | None = None
    rank: int | None = None


class AgentRunPayloadRead(BaseModel):
    """공통 Agent 실행 응답의 실제 생성 결과 영역입니다."""

    draft: str | None = None
    citations: list[AgentCitationRead]
    disclaimer: str | None = None


class AgentRunRead(BaseModel):
    """`/api/ai/agent-runs` 공통 응답입니다."""

    run_id: int
    status: AgentRunStatus
    task_type: AgentTaskType
    agent_provider: str | None
    agent_model_name: str | None
    tool_calls: list[AgentToolCallRead]
    result: AgentRunPayloadRead

    @classmethod
    def from_service_result(cls, result: AgentRunResult) -> "AgentRunRead":
        return cls(
            run_id=result.run_id,
            status=result.status,
            task_type=result.task_type,
            agent_provider=result.agent_provider,
            agent_model_name=result.agent_model_name,
            tool_calls=[
                AgentToolCallRead(
                    step_index=tool_call.step_index,
                    tool_name=tool_call.tool_name,
                    status=tool_call.status,
                )
                for tool_call in result.tool_calls
            ],
            result=AgentRunPayloadRead(
                draft=result.answer,
                citations=_citation_reads(result.citations),
                disclaimer=result.disclaimer,
            ),
        )


class AnswerDraftRead(BaseModel):
    """답변 초안 편의 endpoint 응답입니다."""

    run_id: int
    status: AgentRunStatus
    agent_provider: str | None
    agent_model_name: str | None
    draft: str | None
    citations: list[AgentCitationRead]
    disclaimer: str | None
    tool_calls: list[AgentToolCallRead]

    @classmethod
    def from_service_result(cls, result: AgentRunResult) -> "AnswerDraftRead":
        return cls(
            run_id=result.run_id,
            status=result.status,
            agent_provider=result.agent_provider,
            agent_model_name=result.agent_model_name,
            draft=result.answer,
            citations=_citation_reads(result.citations),
            disclaimer=result.disclaimer,
            tool_calls=_tool_call_reads(result),
        )


class DisputeIssuesRead(BaseModel):
    """쟁점 탐지 편의 endpoint 응답입니다.

    MVP Orchestrator는 구조화된 issue 배열을 강제하지 않고 근거 기반 텍스트를
    생성하므로, API는 우선 `issues_text`로 반환합니다.
    """

    run_id: int
    status: AgentRunStatus
    agent_provider: str | None
    agent_model_name: str | None
    issues_text: str | None
    citations: list[AgentCitationRead]
    disclaimer: str | None
    tool_calls: list[AgentToolCallRead]

    @classmethod
    def from_service_result(cls, result: AgentRunResult) -> "DisputeIssuesRead":
        return cls(
            run_id=result.run_id,
            status=result.status,
            agent_provider=result.agent_provider,
            agent_model_name=result.agent_model_name,
            issues_text=result.answer,
            citations=_citation_reads(result.citations),
            disclaimer=result.disclaimer,
            tool_calls=_tool_call_reads(result),
        )


def _tool_call_reads(result: AgentRunResult) -> list[AgentToolCallRead]:
    return [
        AgentToolCallRead(
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            status=tool_call.status,
        )
        for tool_call in result.tool_calls
    ]


def _citation_reads(citations: list[dict[str, object]]) -> list[AgentCitationRead]:
    return [
        AgentCitationRead(
            chunk_id=_optional_int(citation.get("chunk_id")),
            title=_optional_str(citation.get("title")),
            source_url=_optional_str(citation.get("source_url")),
            heading=_optional_str(citation.get("heading")),
            rank=_optional_int(citation.get("rank")),
        )
        for citation in citations
    ]


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value
