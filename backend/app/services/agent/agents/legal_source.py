"""검색 근거의 충분성을 판단하는 전문 Agent입니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)


class LegalSourceAgent:
    """공식 source 보강 필요성과 다음 단계를 결정합니다."""

    agent_name = "legal_source"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        evidence_count = len(context.evidence_items)
        citation_count = len(context.citations)
        if evidence_count == 0:
            context.metadata["evidence_assessment_reason"] = "no_retrieved_chunks"
            return _insufficient_result(
                reason="no_retrieved_chunks",
                evidence_count=evidence_count,
                citation_count=citation_count,
            )
        if citation_count == 0:
            context.metadata["evidence_assessment_reason"] = "no_citation_candidates"
            return _insufficient_result(
                reason="no_citation_candidates",
                evidence_count=evidence_count,
                citation_count=citation_count,
            )

        context.metadata["evidence_assessment_reason"] = "evidence_available"
        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "evidence_sufficient": True,
                "evidence_count": evidence_count,
                "citation_count": citation_count,
                "reason": "evidence_available",
            },
            handoff=AgentHandoff(
                next_agent="drafting",
                reason="evidence_available_for_draft",
            ),
            confidence=0.75,
        )


def _insufficient_result(
    *,
    reason: str,
    evidence_count: int,
    citation_count: int,
) -> AgentResult:
    return AgentResult(
        agent_name="legal_source",
        status="completed",
        output={
            "evidence_sufficient": False,
            "evidence_count": evidence_count,
            "citation_count": citation_count,
            "reason": reason,
        },
        handoff=AgentHandoff(
            next_agent="safety_review",
            reason="insufficient_evidence_response_required",
            payload={"reason": reason},
        ),
        confidence=0.5,
        requires_human_review=True,
    )
