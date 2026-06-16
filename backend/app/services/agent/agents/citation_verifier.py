"""Citation 검증 action을 계획하는 전문 Agent입니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)


class CitationVerifierAgent:
    """Supervisor가 실행할 citation 검증 tool 호출 계획을 만듭니다."""

    agent_name = "citation_verifier"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        if context.rag_run_id is None:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "rag_run_required"},
                error_code="citation_verifier_run_required",
                error_message="Citation verification requires a RAG run",
            )
        if not context.citations:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "citations_required"},
                error_code="citation_verifier_citations_required",
                error_message="Citation verification requires citations",
            )

        arguments = {
            "run_id": context.rag_run_id,
            "citations": context.citations,
        }
        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "tool_name": "verify_citations",
                "run_id": context.rag_run_id,
                "citation_count": len(context.citations),
            },
            handoff=AgentHandoff(
                next_agent="safety_review",
                reason="citations_ready_for_verification",
                payload={
                    "tool_name": "verify_citations",
                    "arguments": arguments,
                },
            ),
            confidence=0.8,
        )
