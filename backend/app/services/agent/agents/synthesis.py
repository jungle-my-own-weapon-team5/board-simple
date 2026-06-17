"""검증된 도메인 보고서를 종합 답변 prompt로 변환합니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)
from app.services.agent.prompts import build_synthesis_prompt


class SynthesisAgent:
    """도메인별 보고서를 통합해 최종 답변 생성을 준비합니다."""

    agent_name = "synthesis"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        if not context.domain_reports:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "domain_reports_required"},
                error_code="synthesis_domain_reports_required",
                error_message="Synthesis requires domain reports",
            )
        if not context.verified_evidence:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "verified_evidence_required"},
                error_code="synthesis_verified_evidence_required",
                error_message="Synthesis requires verified evidence",
            )

        prompt = build_synthesis_prompt(
            request=context.request,
            domain_reports=context.domain_reports,
            evidence_items=context.verified_evidence,
            citations=context.citations,
        )
        context.synthesis_report = {
            "domain_report_count": len(context.domain_reports),
            "verified_evidence_count": len(context.verified_evidence),
            "citation_count": len(context.citations),
        }
        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "prompt": prompt,
                "prompt_length": len(prompt),
                "domain_report_count": len(context.domain_reports),
                "verified_evidence_count": len(context.verified_evidence),
                "citation_count": len(context.citations),
            },
            handoff=AgentHandoff(
                next_agent="safety_review",
                reason="synthesis_ready_for_safety_review",
            ),
            confidence=0.75,
        )
