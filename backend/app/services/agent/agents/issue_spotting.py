"""사실관계에서 검색 계획을 만드는 전문 Agent입니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)


class IssueSpottingAgent:
    """후보 쟁점과 검색 query를 추출합니다."""

    agent_name = "issue_spotting"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        request = context.request
        issue_plan = {
            "candidate_issues": [_compact_text(request.question)],
            "legal_areas": _guess_legal_areas(request.facts, request.question),
            "candidate_law_names": _candidate_law_names(request.options),
            "internal_rag_query": f"{request.facts}\n{request.question}",
            "external_source_query": request.question or request.facts,
            "search_mode": request.search_mode,
        }
        context.issue_plan = issue_plan
        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "candidate_issue_count": len(issue_plan["candidate_issues"]),
                "legal_areas": issue_plan["legal_areas"],
                "has_internal_rag_query": True,
            },
            handoff=AgentHandoff(
                next_agent="retrieval",
                reason="issue_plan_ready",
                payload={"search_mode": request.search_mode},
            ),
            confidence=0.6,
        )


def _compact_text(value: str) -> str:
    normalized = " ".join(value.strip().split())
    return normalized[:120] if normalized else "사용자 질의"


def _candidate_law_names(options: dict[str, object]) -> list[str]:
    law_names = options.get("candidate_law_names")
    if not isinstance(law_names, list):
        return []
    return [name.strip() for name in law_names if isinstance(name, str) and name.strip()]


def _guess_legal_areas(facts: str, question: str) -> list[str]:
    text = f"{facts} {question}"
    areas: list[str] = []
    if any(keyword in text for keyword in ["사기", "폭행", "협박", "절도", "형사"]):
        areas.append("criminal")
    if any(keyword in text for keyword in ["계약", "보증금", "손해배상", "임대차"]):
        areas.append("civil")
    if any(keyword in text for keyword in ["처분", "허가", "행정", "과징금"]):
        areas.append("administrative")
    return areas or ["general"]
