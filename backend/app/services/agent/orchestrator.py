"""MVP 단일 Orchestrator Agent 구현입니다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.rag_run import AgentStep, RagRun
from app.repositories import agent_steps as agent_step_repository
from app.repositories import rag_runs as rag_run_repository
from app.services.agent.citations import build_chunk_citations
from app.services.agent.prompts import build_draft_prompt
from app.services.agent.state import (
    AgentAction,
    AgentActionType,
    EvidenceAssessment,
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
from app.services.rag.embedding_profiles import (
    EmbeddingProfileConfigError,
    get_active_or_create_default_embedding_profile,
)
from app.services.rag.legal_open_api import LawOpenApiClient
from app.services.rag.legal_open_api_sync import sync_and_embed_law_open_api_statute
from app.services.rag.legal_source_planner import (
    LegalSourceCandidate,
    plan_legal_source_candidates,
)

ALLOWED_ACTION_TYPES: set[str] = {
    "search_internal",
    "search_external_source",
    "sync_official_source",
    "draft_answer",
    "verify_citations",
    "respond_insufficient_evidence",
    "stop",
}
ACTION_TOOL_NAMES: dict[str, str] = {
    "search_internal": "search_legal_documents",
    "search_external_source": "search_law_open_api",
    "verify_citations": "verify_citations",
}


@dataclass(frozen=True)
class _OfficialSourceEnrichmentResult:
    rag_run: RagRun
    evidence_items: list[dict[str, object]]
    citations: list[dict[str, object]]
    step_index: int
    tool_call_count: int
    iteration_count: int


class AgentActionPlanner(Protocol):
    """LLM 또는 deterministic planner가 다음 action을 제안하는 계약입니다."""

    def propose_search_action(self, request: AgentRunRequest) -> AgentAction:
        """내부 RAG 검색 action을 제안합니다."""

    def propose_verify_action(
        self,
        *,
        rag_run_id: int,
        citations: list[dict[str, object]],
    ) -> AgentAction:
        """Citation 검증 action을 제안합니다."""

    def propose_external_source_action(
        self,
        request: AgentRunRequest,
        assessment: EvidenceAssessment,
    ) -> AgentAction:
        """내부 RAG 근거 부족 시 외부 공식 source 조회 action을 제안합니다."""

    def propose_sync_official_source_action(
        self,
        request: AgentRunRequest,
        external_source_result: dict[str, Any],
    ) -> AgentAction:
        """외부 공식 source 후보를 공용 corpus로 보강하는 action을 제안합니다."""


class DefaultAgentActionPlanner:
    """현재 MVP의 deterministic action planner입니다."""

    def propose_search_action(self, request: AgentRunRequest) -> AgentAction:
        return _build_search_action(request)

    def propose_verify_action(
        self,
        *,
        rag_run_id: int,
        citations: list[dict[str, object]],
    ) -> AgentAction:
        return _build_verify_action(rag_run_id=rag_run_id, citations=citations)

    def propose_external_source_action(
        self,
        request: AgentRunRequest,
        assessment: EvidenceAssessment,
    ) -> AgentAction:
        return AgentAction(
            action_type="search_external_source",
            tool_name="search_law_open_api",
            arguments={
                "query": _official_source_query(request),
                "target": "statute",
                "limit": 1,
            },
            reason=f"internal_evidence_insufficient:{assessment.reason}",
        )

    def propose_sync_official_source_action(
        self,
        request: AgentRunRequest,
        external_source_result: dict[str, Any],
    ) -> AgentAction:
        return AgentAction(
            action_type="sync_official_source",
            arguments={"query": _official_sync_query(request, external_source_result)},
            reason="sync_first_official_source_candidate",
        )


class OrchestratorAgent:
    """MCP tool을 순서대로 호출하는 MVP 단일 Agent입니다."""

    def __init__(
        self,
        *,
        settings: Settings,
        ai_client: AIClient | None = None,
        mcp_server: McpJsonRpcServer | None = None,
        action_planner: AgentActionPlanner | None = None,
        law_open_api_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.ai_client = ai_client or AIClient(settings)
        self.mcp_server = mcp_server or create_default_server(
            settings.mcp_allowed_tool_names
        )
        self.action_planner = action_planner or DefaultAgentActionPlanner()
        self.law_open_api_client = law_open_api_client

    def run(self, db: Session, request: AgentRunRequest) -> AgentRunResult:
        normalized_request = _validate_request(request)
        step_index = 1
        tool_calls: list[AgentToolCallSummary] = []
        rag_run: RagRun | None = None
        tool_call_count = 0
        iteration_count = 0
        seen_actions: dict[str, int] = {}

        try:
            search_action = self.action_planner.propose_search_action(
                normalized_request
            )
            iteration_count = _next_iteration_count(
                iteration_count,
                settings=self.settings,
            )
            search_validation = _validate_action(
                search_action,
                settings=self.settings,
                seen_actions=seen_actions,
                allowed_action_types={"search_internal"},
            )
            _record_action_seen(search_action, seen_actions)
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
                output_json=search_validation,
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

            evidence_items = _filter_relevant_evidence_items(
                _require_search_items(search_result),
                settings=self.settings,
            )
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

            assessment = _assess_evidence(
                evidence_items,
                citations,
                settings=self.settings,
            )
            if not assessment.is_sufficient:
                _add_step(
                    db,
                    rag_run=rag_run,
                    step_index=step_index,
                    step_type="decide_continue_or_stop",
                    status="completed",
                    output_json={
                        "decision": "search_external_source",
                        "reason": assessment.reason,
                    },
                )
                step_index += 1

                enrichment_result = self._try_enrich_official_sources(
                    db,
                    request=normalized_request,
                    rag_run=rag_run,
                    assessment=assessment,
                    step_index=step_index,
                    iteration_count=iteration_count,
                    seen_actions=seen_actions,
                    tool_calls=tool_calls,
                    tool_call_count=tool_call_count,
                )
                if enrichment_result is None:
                    return self._complete_with_insufficient_evidence(
                        db,
                        rag_run=rag_run,
                        request=normalized_request,
                        step_index=step_index,
                        assessment=assessment,
                        tool_calls=tool_calls,
                    )
                rag_run = enrichment_result.rag_run
                evidence_items = enrichment_result.evidence_items
                citations = enrichment_result.citations
                step_index = enrichment_result.step_index
                tool_call_count = enrichment_result.tool_call_count
                iteration_count = enrichment_result.iteration_count
                assessment = _assess_evidence(
                    evidence_items,
                    citations,
                    settings=self.settings,
                )
                if not assessment.is_sufficient:
                    return self._complete_with_insufficient_evidence(
                        db,
                        rag_run=rag_run,
                        request=normalized_request,
                        step_index=step_index,
                        assessment=assessment,
                        tool_calls=tool_calls,
                    )
            else:
                _add_step(
                    db,
                    rag_run=rag_run,
                    step_index=step_index,
                    step_type="decide_continue_or_stop",
                    status="completed",
                    output_json={"decision": "draft", "reason": assessment.reason},
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

            verify_action = self.action_planner.propose_verify_action(
                rag_run_id=rag_run.id,
                citations=citations,
            )
            iteration_count = _next_iteration_count(
                iteration_count,
                settings=self.settings,
            )
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

            verify_validation = _validate_action(
                verify_action,
                settings=self.settings,
                seen_actions=seen_actions,
                allowed_action_types={"verify_citations"},
            )
            _record_action_seen(verify_action, seen_actions)
            _add_step(
                db,
                rag_run=rag_run,
                step_index=step_index,
                step_type="validate_action",
                tool_name=verify_action.tool_name,
                status="completed",
                input_json=_action_validation_input(verify_action),
                output_json=verify_validation,
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
                law_open_api_client=self.law_open_api_client,
            ),
        )

    def _try_enrich_official_sources(
        self,
        db: Session,
        *,
        request: AgentRunRequest,
        rag_run: RagRun,
        assessment: EvidenceAssessment,
        step_index: int,
        iteration_count: int,
        seen_actions: dict[str, int],
        tool_calls: list[AgentToolCallSummary],
        tool_call_count: int,
    ) -> _OfficialSourceEnrichmentResult | None:
        if not self.settings.law_open_api_oc.strip() and self.law_open_api_client is None:
            return None

        source_candidates = self._plan_official_source_candidates(request)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="plan_official_sources",
            status="completed",
            output_json={
                "candidate_count": len(source_candidates),
                "candidates": [
                    {
                        "document_type": candidate.document_type,
                        "title": candidate.title,
                        "query_length": len(candidate.query),
                    }
                    for candidate in source_candidates
                ],
            },
        )
        step_index += 1

        external_action = _external_source_action_from_candidates(
            request,
            assessment,
            source_candidates,
        ) or self.action_planner.propose_external_source_action(
            request,
            assessment,
        )
        iteration_count = _next_iteration_count(
            iteration_count,
            settings=self.settings,
        )
        external_validation = _validate_action(
            external_action,
            settings=self.settings,
            seen_actions=seen_actions,
            allowed_action_types={"search_external_source"},
        )
        _record_action_seen(external_action, seen_actions)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="propose_action",
            tool_name=external_action.tool_name,
            status="completed",
            output_json=_action_summary(external_action),
        )
        step_index += 1
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="validate_action",
            tool_name=external_action.tool_name,
            status="completed",
            input_json=_action_validation_input(external_action),
            output_json=external_validation,
        )
        step_index += 1

        _ensure_tool_budget_available(tool_call_count, settings=self.settings)
        external_response = self._call_tool(
            db,
            tool_name=_require_tool_name(external_action),
            arguments=external_action.arguments,
            user_id=request.user_id,
        )
        tool_call_count += 1
        external_result = _unwrap_tool_result(external_response)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="execute_tool",
            tool_name=external_action.tool_name,
            status="completed",
            input_json=_safe_tool_arguments(external_action.arguments),
            output_json=_external_source_summary(external_result),
        )
        tool_calls.append(
            AgentToolCallSummary(
                step_index=step_index,
                tool_name=_require_tool_name(external_action),
                status="completed",
            )
        )
        step_index += 1

        external_items = _external_source_items(external_result)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="observe",
            status="completed",
            output_json={
                "action_type": external_action.action_type,
                "external_item_count": len(external_items),
            },
        )
        step_index += 1
        if not external_items:
            return None

        sync_action = self.action_planner.propose_sync_official_source_action(
            request,
            external_result,
        )
        sync_action = _with_preferred_titles(sync_action, source_candidates)
        iteration_count = _next_iteration_count(
            iteration_count,
            settings=self.settings,
        )
        sync_validation = _validate_action(
            sync_action,
            settings=self.settings,
            seen_actions=seen_actions,
            allowed_action_types={"sync_official_source"},
        )
        _record_action_seen(sync_action, seen_actions)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="propose_action",
            status="completed",
            output_json=_action_summary(sync_action),
        )
        step_index += 1
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="validate_action",
            status="completed",
            input_json=_action_validation_input(sync_action),
            output_json=sync_validation,
        )
        step_index += 1

        sync_result = self._sync_official_source(db, sync_action)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="execute_service",
            status="completed",
            input_json=_safe_tool_arguments(sync_action.arguments),
            output_json=sync_result,
        )
        step_index += 1
        if sync_result.get("status") not in {"embedded", "reused"}:
            return None

        rerun_action = self.action_planner.propose_search_action(request)
        iteration_count = _next_iteration_count(
            iteration_count,
            settings=self.settings,
        )
        rerun_validation = _validate_action(
            rerun_action,
            settings=self.settings,
            seen_actions=seen_actions,
            allowed_action_types={"search_internal"},
        )
        _record_action_seen(rerun_action, seen_actions)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="propose_action",
            tool_name=rerun_action.tool_name,
            status="completed",
            output_json=_action_summary(rerun_action),
        )
        step_index += 1
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="validate_action",
            tool_name=rerun_action.tool_name,
            status="completed",
            input_json=_action_validation_input(rerun_action),
            output_json=rerun_validation,
        )
        step_index += 1

        _ensure_tool_budget_available(tool_call_count, settings=self.settings)
        rerun_response = self._call_tool(
            db,
            tool_name=_require_tool_name(rerun_action),
            arguments=rerun_action.arguments,
            user_id=request.user_id,
        )
        tool_call_count += 1
        rerun_result = _unwrap_tool_result(rerun_response)
        rerun_rag_run = _require_rag_run(db, rerun_result)
        _prepare_agent_run(
            rerun_rag_run,
            request=request,
            settings=self.settings,
        )
        _move_agent_steps_to_run(db, from_run=rag_run, to_run=rerun_rag_run)
        rag_run = rerun_rag_run
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="execute_tool",
            tool_name=rerun_action.tool_name,
            status="completed",
            input_json=_safe_tool_arguments(rerun_action.arguments),
            output_json=_search_summary(rerun_result),
        )
        tool_calls.append(
            AgentToolCallSummary(
                step_index=step_index,
                tool_name=_require_tool_name(rerun_action),
                status="completed",
            )
        )
        step_index += 1

        if rerun_result.get("status") != "completed":
            return None
        evidence_items = _filter_relevant_evidence_items(
            _require_search_items(rerun_result),
            settings=self.settings,
        )
        citations = build_chunk_citations(evidence_items)
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="observe",
            status="completed",
            output_json={
                "action_type": rerun_action.action_type,
                "evidence_count": len(evidence_items),
                "citation_count": len(citations),
                "after_official_source_sync": True,
            },
        )
        step_index += 1
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="decide_continue_or_stop",
            status="completed",
            output_json={"decision": "draft", "reason": "official_source_enriched"},
        )
        step_index += 1
        return _OfficialSourceEnrichmentResult(
            rag_run=rag_run,
            evidence_items=evidence_items,
            citations=citations,
            step_index=step_index,
            tool_call_count=tool_call_count,
            iteration_count=iteration_count,
        )

    def _plan_official_source_candidates(
        self,
        request: AgentRunRequest,
    ) -> list[LegalSourceCandidate]:
        plan = plan_legal_source_candidates(
            ai_client=self.ai_client,
            settings=self.settings,
            facts=request.facts,
            question=request.question,
            search_mode=request.search_mode,
            max_candidates=self.settings.ai_source_planner_max_candidates,
        )
        return [
            candidate
            for candidate in plan.candidates
            if candidate.document_type == "statute"
        ][: self.settings.ai_source_planner_max_candidates]

    def _sync_official_source(
        self,
        db: Session,
        action: AgentAction,
    ) -> dict[str, object]:
        query = action.arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "sync_official_source requires a non-empty query",
            )
        preferred_titles = _preferred_titles_from_action(action)
        try:
            embedding_profile = get_active_or_create_default_embedding_profile(
                db,
                self.settings,
            )
        except EmbeddingProfileConfigError as exc:
            raise AgentOrchestrationError(
                "agent_embedding_profile_missing",
                str(exc),
            ) from exc
        client = self.law_open_api_client or LawOpenApiClient(
            oc=self.settings.law_open_api_oc,
            base_url=self.settings.law_open_api_base_url,
            service_url=self.settings.law_open_api_service_url,
            timeout_seconds=self.settings.mcp_request_timeout_seconds,
        )
        result = sync_and_embed_law_open_api_statute(
            db,
            client=client,
            query=query.strip(),
            embedding_profile=embedding_profile,
            ai_client=self.ai_client,
            search_limit=min(max(self.settings.ai_source_planner_max_candidates, 1), 20),
            preferred_titles=preferred_titles,
            timeout_seconds=self.settings.ai_request_timeout_seconds,
            commit=False,
        )
        return {
            "status": result.status,
            "document_id": result.document.id if result.document is not None else None,
            "chunk_count": len(result.chunks or []),
            "body_fetched": result.body_fetched,
            "embeddings_reusable": result.embeddings_reusable,
            "skipped_reason": result.skipped_reason,
        }

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

    def _complete_with_insufficient_evidence(
        self,
        db: Session,
        *,
        rag_run: RagRun,
        request: AgentRunRequest,
        step_index: int,
        assessment: EvidenceAssessment,
        tool_calls: list[AgentToolCallSummary],
    ) -> AgentRunResult:
        rag_run.status = "completed"
        rag_run.answer = _insufficient_evidence_answer(assessment)
        rag_run.disclaimer = LEGAL_AI_DISCLAIMER
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="respond_insufficient_evidence",
            status="completed",
            output_json={
                "reason": assessment.reason,
                "relevant_chunk_count": assessment.relevant_chunk_count,
                "citation_count": assessment.citation_count,
            },
        )
        step_index += 1
        _add_step(
            db,
            rag_run=rag_run,
            step_index=step_index,
            step_type="persist",
            status="completed",
            output_json={"status": "completed", "reason": "insufficient_evidence"},
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


def _external_source_action_from_candidates(
    request: AgentRunRequest,
    assessment: EvidenceAssessment,
    candidates: list[LegalSourceCandidate],
) -> AgentAction | None:
    if not candidates:
        return None
    candidate = candidates[0]
    return AgentAction(
        action_type="search_external_source",
        tool_name="search_law_open_api",
        arguments={
            "query": candidate.query,
            "target": "statute",
            "limit": min(max(len(candidates), 1), 20),
        },
        reason=f"llm_source_planner:{assessment.reason}",
    )


def _with_preferred_titles(
    action: AgentAction,
    candidates: list[LegalSourceCandidate],
) -> AgentAction:
    preferred_titles = _candidate_preferred_titles(candidates)
    if not preferred_titles:
        return action
    return AgentAction(
        action_type=action.action_type,
        tool_name=action.tool_name,
        arguments={**action.arguments, "preferred_titles": preferred_titles},
        reason=action.reason,
    )


def _candidate_preferred_titles(candidates: list[LegalSourceCandidate]) -> list[str]:
    titles: list[str] = []
    for candidate in candidates:
        for value in (candidate.title, candidate.query):
            if value.strip() and value not in titles:
                titles.append(value)
    return titles


def _preferred_titles_from_action(action: AgentAction) -> list[str] | None:
    value = action.arguments.get("preferred_titles")
    if not isinstance(value, list):
        return None
    titles = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return titles or None


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


def _next_iteration_count(iteration_count: int, *, settings: Settings) -> int:
    next_count = iteration_count + 1
    if next_count > settings.ai_agent_max_iterations:
        raise AgentOrchestrationError(
            "agent_iteration_budget_exceeded",
            "Agent iteration budget was exceeded",
        )
    return next_count


def _ensure_tool_budget_available(tool_call_count: int, *, settings: Settings) -> None:
    if tool_call_count >= settings.ai_agent_max_tool_calls:
        raise AgentOrchestrationError(
            "agent_tool_budget_exceeded",
            "Agent tool call budget was exceeded",
        )


def _validate_action(
    action: AgentAction,
    *,
    settings: Settings,
    seen_actions: dict[str, int],
    allowed_action_types: set[AgentActionType],
) -> dict[str, object]:
    if action.action_type not in ALLOWED_ACTION_TYPES:
        raise AgentOrchestrationError(
            "agent_action_not_allowed",
            "Agent action type is not allowed",
        )
    if action.action_type not in allowed_action_types:
        raise AgentOrchestrationError(
            "agent_action_not_allowed_in_state",
            "Agent action type is not allowed in the current state",
        )

    expected_tool_name = ACTION_TOOL_NAMES.get(action.action_type)
    if expected_tool_name is None:
        if action.tool_name is not None:
            raise AgentOrchestrationError(
                "agent_action_tool_mismatch",
                "Agent action must not include a tool name",
            )
    elif action.tool_name != expected_tool_name:
        raise AgentOrchestrationError(
            "agent_action_tool_mismatch",
            "Agent action tool name is not allowed",
        )

    if action.tool_name is not None and action.tool_name not in settings.mcp_allowed_tool_names:
        raise AgentOrchestrationError(
            "agent_tool_not_allowed",
            "Agent tool is not in the MCP allowlist",
        )

    _validate_action_arguments(action)

    action_signature = _action_signature(action)
    repeated_count = seen_actions.get(action_signature, 0)
    if repeated_count >= settings.ai_agent_max_repeated_actions:
        raise AgentOrchestrationError(
            "agent_repeated_action_limit_exceeded",
            "Agent repeated action limit was exceeded",
        )

    return {
        "valid": True,
        "action_type": action.action_type,
        "tool_name": action.tool_name,
        "reason": "action_schema_and_policy_valid",
        "previous_same_action_count": repeated_count,
    }


def _validate_action_arguments(action: AgentAction) -> None:
    if action.action_type == "search_internal":
        query = action.arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "search_internal requires a non-empty query",
            )
        search_mode = action.arguments.get("search_mode")
        if search_mode not in {"focused_answer", "issue_spotting"}:
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "search_internal search_mode is invalid",
            )
    elif action.action_type == "verify_citations":
        run_id = action.arguments.get("run_id")
        citations = action.arguments.get("citations")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "verify_citations requires a positive run_id",
            )
        if not isinstance(citations, list):
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "verify_citations requires a citation list",
            )
    elif action.action_type == "search_external_source":
        query = action.arguments.get("query")
        target = action.arguments.get("target")
        if not isinstance(query, str) or not query.strip():
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "search_external_source requires a non-empty query",
            )
        if target not in {"statute", "case", "interpretation", "admin_appeal"}:
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "search_external_source target is invalid",
            )
    elif action.action_type == "sync_official_source":
        query = action.arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise AgentOrchestrationError(
                "agent_action_arguments_invalid",
                "sync_official_source requires a non-empty query",
            )


def _action_signature(action: AgentAction) -> str:
    return repr((action.action_type, action.tool_name, action.arguments))


def _record_action_seen(
    action: AgentAction,
    seen_actions: dict[str, int],
) -> None:
    action_signature = _action_signature(action)
    seen_actions[action_signature] = seen_actions.get(action_signature, 0) + 1


def _assess_evidence(
    evidence_items: list[dict[str, object]],
    citations: list[dict[str, object]],
    *,
    settings: Settings,
) -> EvidenceAssessment:
    if not evidence_items:
        return EvidenceAssessment(
            is_sufficient=False,
            relevant_chunk_count=0,
            citation_count=len(citations),
            reason="no_retrieved_chunks",
        )
    if not citations:
        return EvidenceAssessment(
            is_sufficient=False,
            relevant_chunk_count=len(evidence_items),
            citation_count=0,
            reason="no_citation_candidates",
        )
    max_score = _max_evidence_score(evidence_items)
    if max_score < settings.rag_min_relevance_score:
        return EvidenceAssessment(
            is_sufficient=False,
            relevant_chunk_count=len(evidence_items),
            citation_count=len(citations),
            reason="low_relevance_score",
        )
    return EvidenceAssessment(
        is_sufficient=True,
        relevant_chunk_count=len(evidence_items),
        citation_count=len(citations),
        reason="evidence_available",
    )


def _max_evidence_score(evidence_items: list[dict[str, object]]) -> float:
    scores = [_evidence_score(item) for item in evidence_items]
    return max(scores) if scores else 0.0


def _evidence_score(item: dict[str, object]) -> float:
    score = item.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return 0.0
    return float(score)


def _insufficient_evidence_answer(assessment: EvidenceAssessment) -> str:
    return (
        "현재 내부 검색과 허용된 공식 source 보강만으로는 답변에 필요한 "
        "citation 근거가 충분하지 않습니다. "
        f"사유: {assessment.reason}. "
        "추가 사실관계나 관련 문서를 보강한 뒤 다시 검색해야 합니다."
    )


def _external_source_items(external_result: dict[str, Any]) -> list[dict[str, object]]:
    items = external_result.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _external_source_summary(external_result: dict[str, Any]) -> dict[str, object]:
    items = _external_source_items(external_result)
    return {
        "tool_name": external_result.get("tool_name"),
        "target": external_result.get("target"),
        "item_count": len(items),
        "total_count": external_result.get("total_count"),
    }


def _official_source_query(request: AgentRunRequest) -> str:
    return request.question.strip() or request.facts.strip()


def _official_sync_query(
    request: AgentRunRequest,
    external_source_result: dict[str, Any],
) -> str:
    for item in _external_source_items(external_source_result):
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return _official_source_query(request)


def _move_agent_steps_to_run(
    db: Session,
    *,
    from_run: RagRun,
    to_run: RagRun,
) -> None:
    for step in agent_step_repository.list_agent_steps_by_run(db, from_run.id):
        step.rag_run_id = to_run.id
    db.flush()


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


def _filter_relevant_evidence_items(
    evidence_items: list[dict[str, object]],
    *,
    settings: Settings,
) -> list[dict[str, object]]:
    return [
        item
        for item in evidence_items
        if _evidence_score(item) >= settings.rag_min_relevance_score
    ]


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
