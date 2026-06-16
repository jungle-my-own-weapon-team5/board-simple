"""답변 초안 생성을 준비하는 전문 Agent입니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)
from app.services.agent.prompts import build_draft_prompt


class DraftingAgent:
    """검색 근거를 provider prompt로 변환합니다."""

    agent_name = "drafting"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        if not context.evidence_items or not context.citations:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "evidence_required_before_drafting"},
                error_code="drafting_evidence_required",
                error_message="Drafting requires retrieved evidence and citations",
            )

        prompt = build_draft_prompt(
            request=context.request,
            evidence_items=context.evidence_items,
            citations=context.citations,
        )
        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "prompt": prompt,
                "prompt_length": len(prompt),
                "evidence_count": len(context.evidence_items),
                "citation_count": len(context.citations),
            },
            handoff=AgentHandoff(
                next_agent="citation_verifier",
                reason="draft_ready_for_citation_verification",
            ),
            confidence=0.7,
        )
