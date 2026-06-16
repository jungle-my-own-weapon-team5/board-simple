"""MVP 단일 Orchestrator Agent 구현입니다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.rag_run import AgentStep, RagRun
from app.repositories import agent_steps as agent_step_repository
from app.repositories import rag_runs as rag_run_repository
from app.services.agent.citations import build_chunk_citations
from app.services.agent.prompts import build_draft_prompt
from app.services.agent.state import (
    AgentAction,
    LEGAL_AI_DISCLAIMER,
    AgentRunRequest,
    AgentRunResult,
    AgentToolCallSummary,
)
from app.services.ai.client import AIClient
from app.services.ai.errors import ProviderError
from app.services.ai.types import AITextRequest, AITextResult
from app.services.mcp.server import McpJsonRpcServer, create_default_server
from app.services.mcp.types import McpToolCallContext


class OrchestratorAgent:
    """MCP tool을 순서대로 호출하는 MVP 단일 Agent입니다."""

    def __init__(
        self,
        *,
        settings: Settings,
        ai_client: AIClient | None = None,
        mcp_server: McpJsonRpcServer | None = None,
    ) -> None:
        self.settings = settings
        self.ai_client = ai_client or AIClient(settings)
        self.mcp_server = mcp_server or create_default_server(
            settings.mcp_allowed_tool_names
        )

    def run(self, db: Session, request: AgentRunRequest) -> AgentRunResult:
        normalized_request = _validate_request(request)
        step_index = 1
        tool_calls: list[AgentToolCallSummary] = []
        rag_run: RagRun | None = None
        tool_call_count = 0

        try:
            search_action = _build_search_action(normalized_request)
            search_response = self._call_tool(
                db,
                tool_name=_require_tool_name(search_action),
                arguments=search_action.arguments,
                user_id=normalized_request.user_id,
            )
            tool_call_count += 1
            search_result = _unwrap_tool_result(search_response)
            rag_run = _require_rag_run(db, search_result)
            _prepare_agent_run(
                rag_run,
                request=normalized_request,
                settings=self.settings,
            )

            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="initialize_run",
                status="completed",
                output_json={
                    "max_iterations": self.settings.ai_agent_max_iterations,
                    "max_tool_calls": self.settings.ai_agent_max_tool_calls,
                },
            )
            step_index += 1

            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="plan_issue_sources",
                status="completed",
                input_json=_task_metadata(normalized_request),
                output_json={
                    "rag_queries": [_redacted_query_summary(search_action.arguments)],
                    "candidate_actions": [
                        "search_internal",
                        "draft_answer",
                        "verify_citations",
                    ],
                },
            )
            step_index += 1

            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="propose_action",
                tool_name=search_action.tool_name,
                status="completed",
                output_json=_action_summary(search_action),
            )
            step_index += 1

            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="validate_action",
                tool_name=search_action.tool_name,
                status="completed",
                input_json=_action_validation_input(search_action),
                output_json={"valid": True, "reason": "default_planner_action"},
            )
            step_index += 1

            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="execute_tool",
                tool_name=search_action.tool_name,
                status="completed",
                input_json=_safe_tool_arguments(search_action.arguments),
                output_json=_search_summary(search_result),
            )
            tool_calls.append(
                AgentToolCallSummary(
                    step_index=step_index,
                    tool_name=_require_tool_name(search_action),
                    status="completed",
                )
            )
            step_index += 1

            if search_result.get("status") != "completed":
                return self._fail_existing_run(
                    db,
                    rag_run=rag_run,
                    request=normalized_request,
                    step_index=step_index,
                    error_code=str(search_result.get("error_code") or "agent_search_failed"),
                    error_message=str(search_result.get("error_message") or "Search failed"),
                    tool_calls=tool_calls,
                )

            evidence_items = _require_search_items(search_result)
            citations = build_chunk_citations(evidence_items)
            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="observe",
                status="completed",
                output_json={
                    "action_type": search_action.action_type,
                    "evidence_count": len(evidence_items),
                    "citation_count": len(citations),
                },
            )
            step_index += 1

            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="decide_continue_or_stop",
                status="completed",
                output_json={"decision": "draft", "reason": "evidence_available"},
            )
            step_index += 1

            if tool_call_count >= self.settings.ai_agent_max_tool_calls:
                return self._fail_existing_run(
                    db,
                    rag_run=rag_run,
                    request=normalized_request,
                    step_index=step_index,
                    error_code="agent_tool_budget_exceeded",
                    error_message="Agent tool call budget was exceeded before verification",
                    tool_calls=tool_calls,
                )

            draft_action = _build_draft_action(normalized_request)
            draft_result = self._draft(normalized_request, evidence_items, citations)
            _apply_draft_result(rag_run, draft_result)
            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="draft",
                status="completed",
                input_json={
                    "action_type": draft_action.action_type,
                    "model": self.settings.ai_agent_model,
                    "evidence_count": len(evidence_items),
                },
                output_json={
                    "text_length": len(draft_result.text),
                    "agent_provider": draft_result.agent_provider,
                    "agent_model_name": draft_result.agent_model_name,
                },
            )
            step_index += 1

            verify_action = _build_verify_action(rag_run_id=rag_run.id, citations=citations)
            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="propose_action",
                tool_name=verify_action.tool_name,
                status="completed",
                output_json=_action_summary(verify_action),
            )
            step_index += 1

            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="validate_action",
                tool_name=verify_action.tool_name,
                status="completed",
                input_json=_action_validation_input(verify_action),
                output_json={"valid": True, "reason": "default_planner_action"},
            )
            step_index += 1

            verify_response = self._call_tool(
                db,
                tool_name=_require_tool_name(verify_action),
                arguments=verify_action.arguments,
                user_id=normalized_request.user_id,
            )
            tool_call_count += 1
            verify_result = _unwrap_tool_result(verify_response)
            verify_status = "completed" if verify_result.get("valid") is True else "failed"
            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="verify",
                tool_name=verify_action.tool_name,
                status=verify_status,
                input_json={
                    "run_id": rag_run.id,
                    "citation_count": len(citations),
                    "action_type": verify_action.action_type,
                },
                output_json={
                    "valid": verify_result.get("valid"),
                    "invalid_count": len(verify_result.get("invalid_citations") or []),
                },
            )
            tool_calls.append(
                AgentToolCallSummary(
                    step_index=step_index,
                    tool_name=_require_tool_name(verify_action),
                    status=verify_status,
                )
            )
            step_index += 1

            if verify_result.get("valid") is not True:
                return self._fail_existing_run(
                    db,
                    rag_run=rag_run,
                    request=normalized_request,
                    step_index=step_index,
                    error_code="agent_citation_verification_failed",
                    error_message="Citation verification failed",
                    tool_calls=tool_calls,
                )

            rag_run.status = "completed"
            rag_run.error_code = None
            rag_run.error_message = None
            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="persist",
                status="completed",
                output_json={"status": "completed"},
            )
            db.commit()
            return _build_result(
                rag_run,
                request=normalized_request,
                citations=citations,
                tool_calls=tool_calls,
            )
        except ProviderError as exc:
            if rag_run is None:
                rag_run = _create_failed_run(
                    db,
                    request=normalized_request,
                    settings=self.settings,
                    error_code=exc.__class__.__name__,
                    error_message=_safe_error_message(exc),
                )
            return self._fail_existing_run(
                db,
                rag_run=rag_run,
                request=normalized_request,
                step_index=step_index,
                error_code=exc.__class__.__name__,
                error_message=_safe_error_message(exc),
                tool_calls=tool_calls,
            )
        except AgentOrchestrationError as exc:
            if rag_run is None:
                rag_run = _create_failed_run(
                    db,
                    request=normalized_request,
                    settings=self.settings,
                    error_code=exc.error_code,
                    error_message=exc.message,
                )
            return self._fail_existing_run(
                db,
                rag_run=rag_run,
                request=normalized_request,
                step_index=step_index,
                error_code=exc.error_code,
                error_message=exc.message,
                tool_calls=tool_calls,
            )

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
            "id": f"agent-{tool_name}",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        return self.mcp_server.handle(
            payload,
            context=McpToolCallContext(
                db=db,
                user_id=user_id,
                settings=self.settings,
                ai_client=self.ai_client,
            ),
        )

    def _draft(
        self,
        request: AgentRunRequest,
        evidence_items: list[dict[str, object]],
        citations: list[dict[str, object]],
    ) -> AITextResult:
        if not self.settings.ai_agent_model.strip():
            raise AgentOrchestrationError(
                "agent_model_missing",
                "AI_AGENT_MODEL is required",
            )
        prompt = build_draft_prompt(
            request=request,
            evidence_items=evidence_items,
            citations=citations,
        )
        return self.ai_client.generate_text(
            AITextRequest(
                prompt=prompt,
                model=self.settings.ai_agent_model,
                temperature=_optional_temperature(request.options.get("temperature")),
                timeout_seconds=self.settings.ai_request_timeout_seconds,
                metadata={"purpose": "agent_draft"},
            )
        )

    def _fail_existing_run(
        self,
        db: Session,
        *,
        rag_run: RagRun,
        request: AgentRunRequest,
        step_index: int,
        error_code: str,
        error_message: str,
        tool_calls: list[AgentToolCallSummary],
    ) -> AgentRunResult:
        rag_run.status = "failed"
        rag_run.error_code = error_code
        rag_run.error_message = error_message
        rag_run.disclaimer = LEGAL_AI_DISCLAIMER
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="error",
            status="failed",
            error_code=error_code,
            error_message=error_message,
        )
        db.commit()
        return _build_result(
            rag_run,
            request=request,
            citations=[],
            tool_calls=tool_calls,
        )


class AgentOrchestrationError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _validate_request(request: AgentRunRequest) -> AgentRunRequest:
    if request.task_type not in {"answer_draft", "dispute_issues"}:
        raise ValueError("task_type must be answer_draft or dispute_issues")
    if request.search_mode not in {"focused_answer", "issue_spotting"}:
        raise ValueError("search_mode must be focused_answer or issue_spotting")
    if request.user_id <= 0:
        raise ValueError("user_id must be positive")
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


def _build_search_arguments(request: AgentRunRequest) -> dict[str, object]:
    arguments: dict[str, object] = {
        "query": f"{request.facts}\n{request.question}",
        "search_mode": request.search_mode,
    }
    if request.top_k is not None:
        arguments["top_k"] = request.top_k
    if request.score_threshold is not None:
        arguments["score_threshold"] = request.score_threshold
    if request.max_chunks_per_document is not None:
        arguments["max_chunks_per_document"] = request.max_chunks_per_document
    return arguments


def _build_search_action(request: AgentRunRequest) -> AgentAction:
    return AgentAction(
        action_type="search_internal",
        tool_name="search_legal_documents",
        arguments=_build_search_arguments(request),
        reason="internal_rag_search_first",
    )


def _build_draft_action(request: AgentRunRequest) -> AgentAction:
    return AgentAction(
        action_type="draft_answer",
        reason=f"draft_{request.task_type}_from_available_evidence",
    )


def _build_verify_action(
    *,
    rag_run_id: int,
    citations: list[dict[str, object]],
) -> AgentAction:
    return AgentAction(
        action_type="verify_citations",
        tool_name="verify_citations",
        arguments={"run_id": rag_run_id, "citations": citations},
        reason="verify_generated_citations",
    )


def _require_tool_name(action: AgentAction) -> str:
    if action.tool_name is None:
        raise AgentOrchestrationError(
            "agent_tool_name_missing",
            f"{action.action_type} requires a tool name",
        )
    return action.tool_name


def _unwrap_tool_result(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if isinstance(error, dict):
        data = error.get("data")
        error_code = "agent_tool_error"
        if isinstance(data, dict) and isinstance(data.get("error_code"), str):
            error_code = data["error_code"]
        message = error.get("message")
        raise AgentOrchestrationError(
            error_code,
            message if isinstance(message, str) else "MCP tool failed",
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise AgentOrchestrationError(
            "agent_tool_invalid_response",
            "MCP tool result was invalid",
        )
    return result


def _require_rag_run(db: Session, search_result: dict[str, Any]) -> RagRun:
    run_id = search_result.get("run_id")
    if not isinstance(run_id, int):
        raise AgentOrchestrationError(
            "agent_search_run_missing",
            "search_legal_documents did not return a run_id",
        )
    rag_run = rag_run_repository.get_rag_run(db, run_id)
    if rag_run is None:
        raise AgentOrchestrationError(
            "agent_search_run_not_found",
            "search_legal_documents returned an unknown run_id",
        )
    return rag_run


def _prepare_agent_run(
    rag_run: RagRun,
    *,
    request: AgentRunRequest,
    settings: Settings,
) -> None:
    rag_run.run_type = request.task_type
    rag_run.query = request.question
    rag_run.facts = request.facts
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
        raise AgentOrchestrationError(
            "agent_search_items_invalid",
            "search_legal_documents returned invalid items",
        )
    return [item for item in items if isinstance(item, dict)]


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


def _task_metadata(request: AgentRunRequest) -> dict[str, object]:
    return {
        "task_type": request.task_type,
        "facts_length": len(request.facts),
        "question_length": len(request.question),
        "search_mode": request.search_mode,
        "top_k": request.top_k,
        "score_threshold": request.score_threshold,
        "max_chunks_per_document": request.max_chunks_per_document,
    }


def _safe_tool_arguments(arguments: dict[str, object]) -> dict[str, object]:
    safe_arguments = dict(arguments)
    query = safe_arguments.pop("query", "")
    citations = safe_arguments.pop("citations", None)
    safe_arguments["query_length"] = len(str(query))
    if isinstance(citations, list):
        safe_arguments["citation_count"] = len(citations)
    return safe_arguments


def _redacted_query_summary(arguments: dict[str, object]) -> dict[str, object]:
    return _safe_tool_arguments(arguments)


def _action_summary(action: AgentAction) -> dict[str, object]:
    return {
        "action_type": action.action_type,
        "tool_name": action.tool_name,
        "reason": action.reason,
        "arguments": _safe_tool_arguments(action.arguments),
    }


def _action_validation_input(action: AgentAction) -> dict[str, object]:
    return {
        "action_type": action.action_type,
        "tool_name": action.tool_name,
        "arguments": _safe_tool_arguments(action.arguments),
    }


def _search_summary(search_result: dict[str, Any]) -> dict[str, object]:
    items = search_result.get("items")
    item_count = len(items) if isinstance(items, list) else 0
    return {
        "run_id": search_result.get("run_id"),
        "status": search_result.get("status"),
        "item_count": item_count,
        "embedding_profile_id": search_result.get("embedding_profile_id"),
    }


def _build_result(
    rag_run: RagRun,
    *,
    request: AgentRunRequest,
    citations: list[dict[str, object]],
    tool_calls: list[AgentToolCallSummary],
) -> AgentRunResult:
    return AgentRunResult(
        run_id=rag_run.id,
        status="completed" if rag_run.status == "completed" else "failed",
        task_type=request.task_type,
        agent_provider=rag_run.agent_provider,
        agent_model_name=rag_run.agent_model_name,
        answer=rag_run.answer,
        citations=citations if rag_run.status == "completed" else [],
        disclaimer=rag_run.disclaimer,
        tool_calls=tool_calls,
        error_code=rag_run.error_code,
        error_message=rag_run.error_message,
    )


def _optional_temperature(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentOrchestrationError(
            "agent_invalid_temperature",
            "temperature must be a number",
        )
    temperature = float(value)
    if not 0 <= temperature <= 2:
        raise AgentOrchestrationError(
            "agent_invalid_temperature",
            "temperature must be between 0 and 2",
        )
    return temperature


def _safe_error_message(exc: Exception) -> str:
    # Provider 예외 메시지는 외부 응답 원문이나 설정값을 포함할 수 있으므로
    # 사용자/감사 로그에는 예외 종류만 남깁니다.
    return exc.__class__.__name__
