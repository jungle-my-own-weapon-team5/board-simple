"""도메인별 보고서의 근거를 전역 evidence index 기준으로 검증합니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)


class EvidenceVerifierAgent:
    """도메인 보고서와 citation 후보를 검증하는 전문 Agent입니다."""

    agent_name = "evidence_verifier"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        if context.rag_run_id is None:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "rag_run_required"},
                error_code="evidence_verifier_run_required",
                error_message="Evidence verification requires a RAG run",
            )
        if not context.domain_reports:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "domain_reports_required"},
                error_code="evidence_verifier_domain_reports_required",
                error_message="Evidence verification requires domain reports",
            )
        if not context.citations:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "citations_required"},
                error_code="evidence_verifier_citations_required",
                error_message="Evidence verification requires citations",
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
                "domain_report_count": len(context.domain_reports),
                "citation_count": len(context.citations),
            },
            handoff=AgentHandoff(
                next_agent="synthesis",
                reason="evidence_ready_for_synthesis",
                payload={
                    "tool_name": "verify_citations",
                    "arguments": arguments,
                },
            ),
            confidence=0.8,
        )
