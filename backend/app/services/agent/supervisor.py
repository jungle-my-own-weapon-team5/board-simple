"""Supervisor 기반 멀티에이전트 workflow 구현입니다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.rag_run import AgentStep, RagRun
from app.repositories import agent_steps as agent_step_repository
from app.repositories import rag_runs as rag_run_repository
from app.services.agent.agents import (
    AdministrativeLawAgent,
    CitationVerifierAgent,
    CivilLawAgent,
    CriminalLawAgent,
    DraftingAgent,
    EvidenceVerifierAgent,
    IssueDomainPlannerAgent,
    IssueSpottingAgent,
    LaborLawAgent,
    LegalSourceAgent,
    LeaseLawAgent,
    RetrievalAgent,
    SafetyReviewAgent,
    SynthesisAgent,
)
from app.services.agent.citations import build_chunk_citations
from app.services.agent.contracts import (
    AgentContext,
    AgentName,
    AgentResult,
    AgentTask,
    SpecializedAgent,
)
from app.services.agent.state import (
    AgentRunRequest,
    AgentRunResult,
    AgentToolCallSummary,
    LEGAL_AI_DISCLAIMER,
)
from app.services.ai.client import AIClient
from app.services.ai.errors import ProviderError
from app.services.ai.types import AITextRequest, AITextResult
from app.services.mcp.server import McpJsonRpcServer, create_default_server
from app.services.mcp.types import McpToolCallContext


@dataclass
class _SupervisorState:
    rag_run: RagRun | None = None
    step_index: int = 1
    agent_run_count: int = 0
    handoff_count: int = 0
    tool_call_count: int = 0


class SupervisorAgent:
    """전문 Agent 호출 순서와 handoff를 관리하는 상위 Agent입니다."""

    def __init__(
        self,
        *,
        settings: Settings,
        ai_client: AIClient | None = None,
        mcp_server: McpJsonRpcServer | None = None,
        agents: dict[AgentName, SpecializedAgent] | None = None,
    ) -> None:
        self.settings = settings
        self.ai_client = ai_client or AIClient(settings)
        self.mcp_server = mcp_server or create_default_server(
            settings.mcp_allowed_tool_names
        )
        self.agents = agents or _default_agents()

    def run(self, db: Session, request: AgentRunRequest) -> AgentRunResult:
        normalized_request = _validate_request(request)
        context = AgentContext(request=normalized_request)
        state = _SupervisorState()
        pending_results: list[tuple[int, AgentTask, AgentResult]] = []
        current_agent: AgentName | None = "domain_planner"

        try:
            while current_agent is not None:
                _ensure_agent_iteration_budget(state, self.settings)
                agent = self._require_agent(current_agent)
                task = AgentTask(agent_name=current_agent)
                result = agent.run(context, task)
                step_index_for_result = state.step_index
                state.step_index += 1

                if state.rag_run is None:
                    pending_results.append((step_index_for_result, task, result))
                else:
                    _add_agent_result_step(
                        db,
                        rag_run=state.rag_run,
                        step_index=step_index_for_result,
                        task=task,
                        result=result,
                    )

                if result.status == "failed":
                    return self._fail(
                        db,
                        context=context,
                        state=state,
                        pending_results=pending_results,
                        error_code=result.error_code or "agent_failed",
                        error_message=result.error_message or "Specialized agent failed",
                    )

                if current_agent == "retrieval":
                    self._execute_retrieval(
                        db,
                        context=context,
                        state=state,
                        pending_results=pending_results,
                        result=result,
                    )
                elif current_agent == "drafting":
                    self._execute_drafting(
                        db,
                        context=context,
                        state=state,
                        result=result,
                    )
                elif current_agent == "citation_verifier":
                    self._execute_citation_verification(
                        db,
                        context=context,
                        state=state,
                        result=result,
                    )
                elif current_agent == "evidence_verifier":
                    self._execute_evidence_verification(
                        db,
                        context=context,
                        state=state,
                        result=result,
                    )
                elif current_agent == "synthesis":
                    self._execute_synthesis(
                        db,
                        context=context,
                        state=state,
                        result=result,
                    )
                elif current_agent == "legal_source" and _needs_insufficient_answer(
                    result
                ):
                    context.answer = _insufficient_evidence_answer(result)

                if result.handoff is None:
                    current_agent = None
                else:
                    _ensure_handoff_budget(state, self.settings)
                    current_agent = result.handoff.next_agent

            if state.rag_run is None:
                return self._fail(
                    db,
                    context=context,
                    state=state,
                    pending_results=pending_results,
                    error_code="supervisor_rag_run_missing",
                    error_message="Supervisor workflow did not create a RAG run",
                )
            if not context.answer:
                return self._fail(
                    db,
                    context=context,
                    state=state,
                    pending_results=pending_results,
                    error_code="supervisor_answer_missing",
                    error_message="Supervisor workflow did not produce an answer",
                )

            state.rag_run.status = "completed"
            state.rag_run.answer = context.answer
            state.rag_run.disclaimer = LEGAL_AI_DISCLAIMER
            state.rag_run.error_code = None
            state.rag_run.error_message = None
            _add_step(
                db,
                rag_run=state.rag_run,
                step_index=state.step_index,
                step_type="multi_agent_persist",
                status="completed",
                output_json={
                    "status": "completed",
                    "agent_run_count": state.agent_run_count,
                    "handoff_count": state.handoff_count,
                    "tool_call_count": state.tool_call_count,
                },
            )
            db.commit()
            return _build_result(state.rag_run, context=context)
        except ProviderError as exc:
            return self._fail(
                db,
                context=context,
                state=state,
                pending_results=pending_results,
                error_code=exc.__class__.__name__,
                error_message=exc.__class__.__name__,
            )
        except SupervisorAgentError as exc:
            return self._fail(
                db,
                context=context,
                state=state,
                pending_results=pending_results,
                error_code=exc.error_code,
                error_message=exc.message,
            )

    def _execute_retrieval(
        self,
        db: Session,
        *,
        context: AgentContext,
        state: _SupervisorState,
        pending_results: list[tuple[int, AgentTask, AgentResult]],
        result: AgentResult,
    ) -> None:
        tool_name, arguments = _tool_from_handoff(
            result,
            expected_tool_name="search_legal_documents",
        )
        _ensure_tool_budget(state, self.settings)
        response = self._call_tool(
            db,
            tool_name=tool_name,
            arguments=arguments,
            user_id=context.request.user_id,
        )
        state.tool_call_count += 1
        search_result = _unwrap_tool_result(response)
        state.rag_run = _require_rag_run(db, search_result)
        _prepare_multi_agent_run(
            state.rag_run,
            request=context.request,
            settings=self.settings,
        )
        context.rag_run_id = state.rag_run.id
        context.evidence_items = _require_search_items(search_result)
        context.citations = build_chunk_citations(context.evidence_items)
        _flush_pending_agent_results(
            db,
            rag_run=state.rag_run,
            pending_results=pending_results,
        )
        _add_step(
            db,
            rag_run=state.rag_run,
            step_index=state.step_index,
            step_type="multi_agent_execute_tool",
            tool_name=tool_name,
            status="completed",
            input_json=_safe_tool_arguments(arguments),
            output_json={
                "status": search_result.get("status"),
                "item_count": len(context.evidence_items),
                "citation_count": len(context.citations),
            },
        )
        context.tool_calls.append(
            AgentToolCallSummary(
                step_index=state.step_index,
                tool_name=tool_name,
                status="completed",
            )
        )
        state.step_index += 1
        if search_result.get("status") != "completed":
            raise SupervisorAgentError(
                str(search_result.get("error_code") or "supervisor_search_failed"),
                str(search_result.get("error_message") or "Search failed"),
            )

    def _execute_drafting(
        self,
        db: Session,
        *,
        context: AgentContext,
        state: _SupervisorState,
        result: AgentResult,
    ) -> None:
        if state.rag_run is None:
            raise SupervisorAgentError(
                "supervisor_rag_run_missing",
                "Drafting requires a RAG run",
            )
        prompt = result.output.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise SupervisorAgentError(
                "supervisor_prompt_missing",
                "Drafting agent did not return a prompt",
            )
        draft_result = self.ai_client.generate_text(
            AITextRequest(
                prompt=prompt,
                model=self.settings.ai_agent_model,
                temperature=_optional_temperature(
                    context.request.options.get("temperature")
                ),
                timeout_seconds=self.settings.ai_request_timeout_seconds,
                metadata={"purpose": "multi_agent_draft"},
            )
        )
        context.draft_result = draft_result
        context.answer = draft_result.text
        _apply_draft_result(state.rag_run, draft_result)
        _add_step(
            db,
            rag_run=state.rag_run,
            step_index=state.step_index,
            step_type="multi_agent_execute_model",
            status="completed",
            input_json={
                "agent_name": "drafting",
                "prompt_length": len(prompt),
                "model": self.settings.ai_agent_model,
            },
            output_json={
                "text_length": len(draft_result.text),
                "agent_provider": draft_result.agent_provider,
                "agent_model_name": draft_result.agent_model_name,
            },
        )
        state.step_index += 1

    def _execute_citation_verification(
        self,
        db: Session,
        *,
        context: AgentContext,
        state: _SupervisorState,
        result: AgentResult,
    ) -> None:
        if state.rag_run is None:
            raise SupervisorAgentError(
                "supervisor_rag_run_missing",
                "Citation verification requires a RAG run",
            )
        tool_name, arguments = _tool_from_handoff(
            result,
            expected_tool_name="verify_citations",
        )
        _ensure_tool_budget(state, self.settings)
        response = self._call_tool(
            db,
            tool_name=tool_name,
            arguments=arguments,
            user_id=context.request.user_id,
        )
        state.tool_call_count += 1
        verify_result = _unwrap_tool_result(response)
        verify_status = "completed" if verify_result.get("valid") is True else "failed"
        _add_step(
            db,
            rag_run=state.rag_run,
            step_index=state.step_index,
            step_type="multi_agent_execute_tool",
            tool_name=tool_name,
            status=verify_status,
            input_json={
                "run_id": state.rag_run.id,
                "citation_count": len(context.citations),
            },
            output_json={
                "valid": verify_result.get("valid"),
                "invalid_count": len(verify_result.get("invalid_citations") or []),
            },
        )
        context.tool_calls.append(
            AgentToolCallSummary(
                step_index=state.step_index,
                tool_name=tool_name,
                status=verify_status,
            )
        )
        state.step_index += 1
        if verify_result.get("valid") is not True:
            raise SupervisorAgentError(
                "supervisor_citation_verification_failed",
                "Citation verification failed",
            )

    def _execute_evidence_verification(
        self,
        db: Session,
        *,
        context: AgentContext,
        state: _SupervisorState,
        result: AgentResult,
    ) -> None:
        if state.rag_run is None:
            raise SupervisorAgentError(
                "supervisor_rag_run_missing",
                "Evidence verification requires a RAG run",
            )
        tool_name, arguments = _tool_from_handoff(
            result,
            expected_tool_name="verify_citations",
        )
        _ensure_tool_budget(state, self.settings)
        response = self._call_tool(
            db,
            tool_name=tool_name,
            arguments=arguments,
            user_id=context.request.user_id,
        )
        state.tool_call_count += 1
        verify_result = _unwrap_tool_result(response)
        verify_status = "completed" if verify_result.get("valid") is True else "failed"
        _add_step(
            db,
            rag_run=state.rag_run,
            step_index=state.step_index,
            step_type="multi_agent_execute_tool",
            tool_name=tool_name,
            status=verify_status,
            input_json={
                "run_id": state.rag_run.id,
                "domain_report_count": len(context.domain_reports),
                "citation_count": len(context.citations),
            },
            output_json={
                "valid": verify_result.get("valid"),
                "invalid_count": len(verify_result.get("invalid_citations") or []),
            },
        )
        context.tool_calls.append(
            AgentToolCallSummary(
                step_index=state.step_index,
                tool_name=tool_name,
                status=verify_status,
            )
        )
        state.step_index += 1
        if verify_result.get("valid") is not True:
            raise SupervisorAgentError(
                "supervisor_evidence_verification_failed",
                "Evidence verification failed",
            )
        context.verified_evidence = list(context.evidence_items)

    def _execute_synthesis(
        self,
        db: Session,
        *,
        context: AgentContext,
        state: _SupervisorState,
        result: AgentResult,
    ) -> None:
        if state.rag_run is None:
            raise SupervisorAgentError(
                "supervisor_rag_run_missing",
                "Synthesis requires a RAG run",
            )
        prompt = result.output.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise SupervisorAgentError(
                "supervisor_prompt_missing",
                "Synthesis agent did not return a prompt",
            )
        synthesis_result = self.ai_client.generate_text(
            AITextRequest(
                prompt=prompt,
                model=self.settings.ai_agent_model,
                temperature=_optional_temperature(
                    context.request.options.get("temperature")
                ),
                timeout_seconds=self.settings.ai_request_timeout_seconds,
                metadata={"purpose": "multi_agent_synthesis"},
            )
        )
        context.draft_result = synthesis_result
        context.answer = synthesis_result.text
        _apply_draft_result(state.rag_run, synthesis_result)
        _add_step(
            db,
            rag_run=state.rag_run,
            step_index=state.step_index,
            step_type="multi_agent_execute_model",
            status="completed",
            input_json={
                "agent_name": "synthesis",
                "prompt_length": len(prompt),
                "model": self.settings.ai_agent_model,
            },
            output_json={
                "text_length": len(synthesis_result.text),
                "agent_provider": synthesis_result.agent_provider,
                "agent_model_name": synthesis_result.agent_model_name,
            },
        )
        state.step_index += 1

    def _call_tool(
        self,
        db: Session,
        *,
        tool_name: str,
        arguments: dict[str, object],
        user_id: int,
    ) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": f"multi-agent-{tool_name}",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        return self.mcp_server.handle(
            payload,
            context=McpToolCallContext(
                request_id=payload["id"],
                settings=self.settings,
                db=db,
                user_id=user_id,
                ai_client=self.ai_client,
            ),
        )

    def _require_agent(self, agent_name: AgentName) -> SpecializedAgent:
        agent = self.agents.get(agent_name)
        if agent is None:
            raise SupervisorAgentError(
                "supervisor_agent_not_found",
                f"Agent is not registered: {agent_name}",
            )
        return agent

    def _fail(
        self,
        db: Session,
        *,
        context: AgentContext,
        state: _SupervisorState,
        pending_results: list[tuple[int, AgentTask, AgentResult]],
        error_code: str,
        error_message: str,
    ) -> AgentRunResult:
        if state.rag_run is None:
            state.rag_run = _create_failed_run(
                db,
                request=context.request,
                settings=self.settings,
                error_code=error_code,
                error_message=error_message,
            )
            context.rag_run_id = state.rag_run.id
            _flush_pending_agent_results(
                db,
                rag_run=state.rag_run,
                pending_results=pending_results,
            )
        state.rag_run.status = "failed"
        state.rag_run.error_code = error_code
        state.rag_run.error_message = error_message
        _add_step(
            db,
            rag_run=state.rag_run,
            step_index=state.step_index,
            step_type="multi_agent_error",
            status="failed",
            output_json={
                "agent_run_count": state.agent_run_count,
                "handoff_count": state.handoff_count,
                "tool_call_count": state.tool_call_count,
            },
            error_code=error_code,
            error_message=error_message,
        )
        db.commit()
        return _build_result(state.rag_run, context=context)


class SupervisorAgentError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _default_agents() -> dict[AgentName, SpecializedAgent]:
    return {
        "domain_planner": IssueDomainPlannerAgent(),
        "criminal_law": CriminalLawAgent(),
        "civil_law": CivilLawAgent(),
        "labor_law": LaborLawAgent(),
        "administrative_law": AdministrativeLawAgent(),
        "lease_law": LeaseLawAgent(),
        "evidence_verifier": EvidenceVerifierAgent(),
        "synthesis": SynthesisAgent(),
        "issue_spotting": IssueSpottingAgent(),
        "retrieval": RetrievalAgent(),
        "legal_source": LegalSourceAgent(),
        "drafting": DraftingAgent(),
        "citation_verifier": CitationVerifierAgent(),
        "safety_review": SafetyReviewAgent(),
    }


def _validate_request(request: AgentRunRequest) -> AgentRunRequest:
    if request.user_id <= 0:
        raise ValueError("user_id must be positive")
    if request.task_type not in {"answer_draft", "dispute_issues"}:
        raise ValueError("task_type must be answer_draft or dispute_issues")
    if request.search_mode not in {"focused_answer", "issue_spotting"}:
        raise ValueError("search_mode must be focused_answer or issue_spotting")
    if not request.facts.strip():
        raise ValueError("facts must not be blank")
    if not request.question.strip():
        raise ValueError("question must not be blank")
    return AgentRunRequest(
        user_id=request.user_id,
        task_type=request.task_type,
        facts=request.facts.strip(),
        question=request.question.strip(),
        search_mode=request.search_mode,
        top_k=request.top_k,
        score_threshold=request.score_threshold,
        max_chunks_per_document=request.max_chunks_per_document,
        options=dict(request.options),
    )


def _ensure_agent_iteration_budget(
    state: _SupervisorState,
    settings: Settings,
) -> None:
    next_count = state.agent_run_count + 1
    if next_count > settings.ai_agent_max_iterations:
        raise SupervisorAgentError(
            "supervisor_iteration_budget_exceeded",
            "Supervisor agent iteration budget was exceeded",
        )
    state.agent_run_count = next_count


def _ensure_handoff_budget(state: _SupervisorState, settings: Settings) -> None:
    next_count = state.handoff_count + 1
    if next_count > settings.ai_agent_max_handoffs:
        raise SupervisorAgentError(
            "supervisor_handoff_budget_exceeded",
            "Supervisor agent handoff budget was exceeded",
        )
    state.handoff_count = next_count


def _ensure_tool_budget(state: _SupervisorState, settings: Settings) -> None:
    if state.tool_call_count >= settings.ai_agent_max_tool_calls:
        raise SupervisorAgentError(
            "supervisor_tool_budget_exceeded",
            "Supervisor tool call budget was exceeded",
        )


def _flush_pending_agent_results(
    db: Session,
    *,
    rag_run: RagRun,
    pending_results: list[tuple[int, AgentTask, AgentResult]],
) -> None:
    for step_index, task, result in pending_results:
        _add_agent_result_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            task=task,
            result=result,
        )
    pending_results.clear()


def _add_agent_result_step(
    db: Session,
    *,
    rag_run: RagRun,
    step_index: int,
    task: AgentTask,
    result: AgentResult,
) -> None:
    _add_step(
        db,
        rag_run=rag_run,
        step_index=step_index,
        step_type=f"agent_{result.agent_name}",
        status=result.status,
        input_json={
            "agent_name": task.agent_name,
            "input": _safe_json(task.input),
        },
        output_json={
            "output": _safe_agent_output(result.output),
            "handoff": _safe_handoff(result),
            "confidence": result.confidence,
            "requires_human_review": result.requires_human_review,
        },
        error_code=result.error_code,
        error_message=result.error_message,
    )


def _add_step(
    db: Session,
    *,
    rag_run: RagRun,
    step_index: int,
    step_type: str,
    status: str,
    tool_name: str | None = None,
    input_json: dict[str, object] | None = None,
    output_json: dict[str, object] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    now = datetime.now(UTC)
    step = AgentStep(
        rag_run_id=rag_run.id,
        step_index=step_index,
        step_type=step_type,
        tool_name=tool_name,
        status=status,
        input_json=input_json,
        output_json=output_json,
        error_code=error_code,
        error_message=error_message,
        started_at=now,
        finished_at=now,
    )
    agent_step_repository.add_agent_step(db, step)
    db.flush()


def _tool_from_handoff(
    result: AgentResult,
    *,
    expected_tool_name: str,
) -> tuple[str, dict[str, object]]:
    if result.handoff is None:
        raise SupervisorAgentError(
            "supervisor_handoff_missing",
            f"{result.agent_name} did not return a handoff",
        )
    tool_name = result.handoff.payload.get("tool_name")
    arguments = result.handoff.payload.get("arguments")
    if tool_name != expected_tool_name:
        raise SupervisorAgentError(
            "supervisor_tool_mismatch",
            f"{result.agent_name} requested an invalid tool",
        )
    if not isinstance(arguments, dict):
        raise SupervisorAgentError(
            "supervisor_tool_arguments_invalid",
            f"{result.agent_name} did not return tool arguments",
        )
    return tool_name, arguments


def _unwrap_tool_result(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if isinstance(error, dict):
        data = error.get("data")
        error_code = "supervisor_tool_error"
        if isinstance(data, dict) and isinstance(data.get("error_code"), str):
            error_code = data["error_code"]
        message = error.get("message")
        raise SupervisorAgentError(
            error_code,
            message if isinstance(message, str) else "MCP tool failed",
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise SupervisorAgentError(
            "supervisor_tool_invalid_response",
            "MCP tool result was invalid",
        )
    return result


def _require_rag_run(db: Session, search_result: dict[str, Any]) -> RagRun:
    run_id = search_result.get("run_id")
    if not isinstance(run_id, int):
        raise SupervisorAgentError(
            "supervisor_search_run_missing",
            "search_legal_documents did not return a run_id",
        )
    rag_run = rag_run_repository.get_rag_run(db, run_id)
    if rag_run is None:
        raise SupervisorAgentError(
            "supervisor_search_run_not_found",
            "search_legal_documents returned an unknown run_id",
        )
    return rag_run


def _prepare_multi_agent_run(
    rag_run: RagRun,
    *,
    request: AgentRunRequest,
    settings: Settings,
) -> None:
    rag_run.run_type = request.task_type
    rag_run.query = request.question
    rag_run.facts = request.facts
    rag_run.status = "pending"
    rag_run.disclaimer = LEGAL_AI_DISCLAIMER
    rag_run.agent_provider = settings.ai_agent_provider
    rag_run.agent_model_name = settings.ai_agent_model
    rag_run.prompt_version = settings.rag_prompt_version


def _apply_draft_result(rag_run: RagRun, draft_result: AITextResult) -> None:
    rag_run.answer = draft_result.text
    rag_run.disclaimer = LEGAL_AI_DISCLAIMER
    rag_run.agent_provider = draft_result.agent_provider
    rag_run.agent_model_name = draft_result.agent_model_name


def _create_failed_run(
    db: Session,
    *,
    request: AgentRunRequest,
    settings: Settings,
    error_code: str,
    error_message: str,
) -> RagRun:
    rag_run = RagRun(
        user_id=request.user_id,
        run_type=request.task_type,
        query=request.question,
        facts=request.facts,
        status="failed",
        answer=None,
        disclaimer=LEGAL_AI_DISCLAIMER,
        agent_provider=settings.ai_agent_provider,
        agent_model_name=settings.ai_agent_model,
        embedding_profile_id=None,
        embedding_provider=settings.ai_embedding_provider,
        embedding_model_name=settings.ai_embedding_model,
        embedding_dimensions=settings.ai_embedding_dimensions,
        prompt_version=settings.rag_prompt_version,
        error_code=error_code,
        error_message=error_message,
    )
    rag_run_repository.add_rag_run(db, rag_run)
    db.flush()
    return rag_run


def _require_search_items(search_result: dict[str, Any]) -> list[dict[str, object]]:
    items = search_result.get("items")
    if not isinstance(items, list):
        raise SupervisorAgentError(
            "supervisor_search_items_invalid",
            "search_legal_documents returned invalid items",
        )
    return [item for item in items if isinstance(item, dict)]


def _needs_insufficient_answer(result: AgentResult) -> bool:
    return result.handoff is not None and result.handoff.next_agent == "safety_review"


def _insufficient_evidence_answer(result: AgentResult) -> str:
    reason = result.output.get("reason") or "insufficient_evidence"
    return (
        "현재 내부 검색 결과만으로는 답변에 필요한 citation 근거가 충분하지 않습니다. "
        f"사유: {reason}. "
        "공식 source 보강 또는 추가 문서 등록 후 다시 검토해야 합니다."
    )


def _build_result(rag_run: RagRun, *, context: AgentContext) -> AgentRunResult:
    return AgentRunResult(
        run_id=rag_run.id,
        status="completed" if rag_run.status == "completed" else "failed",
        task_type=context.request.task_type,
        agent_provider=rag_run.agent_provider,
        agent_model_name=rag_run.agent_model_name,
        answer=rag_run.answer,
        citations=context.citations if rag_run.status == "completed" else [],
        disclaimer=rag_run.disclaimer,
        tool_calls=context.tool_calls,
        error_code=rag_run.error_code,
        error_message=rag_run.error_message,
    )


def _safe_tool_arguments(arguments: dict[str, object]) -> dict[str, object]:
    safe_arguments = dict(arguments)
    query = safe_arguments.pop("query", "")
    citations = safe_arguments.pop("citations", None)
    safe_arguments["query_length"] = len(str(query))
    if isinstance(citations, list):
        safe_arguments["citation_count"] = len(citations)
    return safe_arguments


def _safe_agent_output(output: dict[str, object]) -> dict[str, object]:
    safe_output = dict(output)
    prompt = safe_output.pop("prompt", None)
    if isinstance(prompt, str):
        safe_output["prompt_length"] = len(prompt)
    return _safe_json(safe_output)


def _safe_handoff(result: AgentResult) -> dict[str, object] | None:
    if result.handoff is None:
        return None
    payload = dict(result.handoff.payload)
    arguments = payload.get("arguments")
    if isinstance(arguments, dict):
        payload["arguments"] = _safe_tool_arguments(arguments)
    return {
        "next_agent": result.handoff.next_agent,
        "reason": result.handoff.reason,
        "payload": _safe_json(payload),
    }


def _safe_json(value: dict[str, object]) -> dict[str, object]:
    safe_value: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            safe_value[key] = _safe_json(item)
        elif isinstance(item, list):
            safe_value[key] = [
                _safe_json(element)
                if isinstance(element, dict)
                else element
                for element in item
            ]
        else:
            safe_value[key] = item
    return safe_value


def _optional_temperature(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SupervisorAgentError(
            "supervisor_invalid_temperature",
            "temperature must be a number",
        )
    temperature = float(value)
    if not 0 <= temperature <= 2:
        raise SupervisorAgentError(
            "supervisor_invalid_temperature",
            "temperature must be between 0 and 2",
        )
    return temperature
