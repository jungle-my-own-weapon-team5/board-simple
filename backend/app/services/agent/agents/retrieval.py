"""내부 RAG 검색 action을 계획하는 전문 Agent입니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)


class RetrievalAgent:
    """Supervisor가 실행할 내부 RAG 검색 tool 호출 계획을 만듭니다."""

    agent_name = "retrieval"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        request = context.request
        query = context.issue_plan.get("internal_rag_query")
        if not isinstance(query, str) or not query.strip():
            query = f"{request.facts}\n{request.question}"

        arguments: dict[str, object] = {
            "query": query,
            "search_mode": request.search_mode,
        }
        if request.top_k is not None:
            arguments["top_k"] = request.top_k
        if request.score_threshold is not None:
            arguments["score_threshold"] = request.score_threshold
        if request.max_chunks_per_document is not None:
            arguments["max_chunks_per_document"] = request.max_chunks_per_document

        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "tool_name": "search_legal_documents",
                "arguments": _safe_arguments(arguments),
            },
            handoff=AgentHandoff(
                next_agent="legal_source",
                reason="internal_retrieval_planned",
                payload={
                    "tool_name": "search_legal_documents",
                    "arguments": arguments,
                },
            ),
            confidence=0.7,
        )


def _safe_arguments(arguments: dict[str, object]) -> dict[str, object]:
    safe_arguments = dict(arguments)
    query = safe_arguments.pop("query", "")
    safe_arguments["query_length"] = len(str(query))
    return safe_arguments
