"""최종 응답 안전성 검토 전문 Agent입니다."""

from __future__ import annotations

from app.services.agent.contracts import AgentContext, AgentResult, AgentTask
from app.services.agent.state import LEGAL_AI_DISCLAIMER

BLOCKED_TEXT_MARKERS = ("API_KEY", "SECRET", "Bearer ")


class SafetyReviewAgent:
    """최종 응답에 citation/disclaimer/secret 노출 문제가 없는지 점검합니다."""

    agent_name = "safety_review"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        answer = context.answer or ""
        if not answer.strip():
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "answer_required"},
                error_code="safety_answer_required",
                error_message="Safety review requires an answer",
            )
        if any(marker in answer for marker in BLOCKED_TEXT_MARKERS):
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "secret_like_text_detected"},
                error_code="safety_secret_like_text_detected",
                error_message="Safety review detected secret-like text",
            )

        citation_required = bool(context.evidence_items)
        citation_ok = not citation_required or bool(context.citations)
        if not citation_ok:
            return AgentResult(
                agent_name=self.agent_name,
                status="failed",
                output={"reason": "citation_required"},
                error_code="safety_citation_required",
                error_message="Safety review requires citations for evidence-backed answers",
            )

        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "disclaimer": LEGAL_AI_DISCLAIMER,
                "citation_count": len(context.citations),
                "secret_like_text_detected": False,
            },
            confidence=0.7,
        )
