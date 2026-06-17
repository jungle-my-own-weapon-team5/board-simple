"""도메인 전문 Agent 실행을 위한 작업 계획을 만듭니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentResult,
    AgentTask,
)

DOMAIN_AGENT_BY_DOMAIN = {
    "criminal": "criminal_law",
    "lease": "lease_law",
    "civil": "civil_law",
    "labor": "labor_law",
    "administrative": "administrative_law",
}


class IssueDomainPlannerAgent:
    """사실관계에서 필요한 법률 도메인과 도메인별 작업을 선별합니다."""

    agent_name = "domain_planner"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        request = context.request
        domains = _select_domains(request.facts, request.question)
        domain_tasks = [
            _domain_task(
                domain=domain,
                facts=request.facts,
                question=request.question,
            )
            for domain in domains
        ]
        context.domain_tasks = domain_tasks
        context.issue_plan = {
            "legal_domains": domains,
            "domain_tasks": domain_tasks,
            "candidate_issues": [task["title"] for task in domain_tasks],
            "internal_rag_query": _combined_query(
                facts=request.facts,
                question=request.question,
                domain_tasks=domain_tasks,
            ),
            "external_source_query": request.question or request.facts,
            "search_mode": request.search_mode,
        }

        return AgentResult(
            agent_name=self.agent_name,
            status="completed",
            output={
                "legal_domains": domains,
                "domain_task_count": len(domain_tasks),
                "domain_agents": [
                    task["agent_name"] for task in domain_tasks
                ],
            },
            handoff=AgentHandoff(
                next_agent="retrieval",
                reason="domain_plan_ready",
                payload={"selected_domains": domains},
            ),
            confidence=0.65,
        )


def _select_domains(facts: str, question: str) -> list[str]:
    text = f"{facts} {question}"
    domains: list[str] = []
    if _contains_any(
        text,
        [
            "살인",
            "사망",
            "죽",
            "시체",
            "시신",
            "자수",
            "범죄",
            "형사",
            "경찰",
            "검찰",
        ],
    ):
        domains.append("criminal")
    if _contains_any(text, ["임대차", "보증금", "차임", "임대인", "임차인", "명도"]):
        domains.append("lease")
    if _contains_any(
        text,
        ["계약", "손해배상", "불법행위", "채무", "민사", "대여금", "소유권"],
    ):
        domains.append("civil")
    if _contains_any(text, ["해고", "임금", "근로", "노동", "산재", "퇴직금"]):
        domains.append("labor")
    if _contains_any(text, ["처분", "허가", "행정", "과징금", "영업정지", "취소소송"]):
        domains.append("administrative")

    # 임대차 쟁점은 민사 일반 쟁점과 함께 검토되는 경우가 많습니다.
    if "lease" in domains and "civil" not in domains:
        domains.append("civil")
    return domains or ["civil"]


def _domain_task(*, domain: str, facts: str, question: str) -> dict[str, object]:
    agent_name = DOMAIN_AGENT_BY_DOMAIN[domain]
    return {
        "domain": domain,
        "agent_name": agent_name,
        "facts_slice": _facts_slice_for_domain(domain=domain, facts=facts),
        "title": _title_for_domain(domain),
        "issue_query": _issue_query_for_domain(
            domain=domain,
            facts=facts,
            question=question,
        ),
    }


def _facts_slice_for_domain(*, domain: str, facts: str) -> str:
    normalized = " ".join(facts.strip().split())
    if len(normalized) <= 500:
        return normalized
    return f"{normalized[:500]}..."


def _title_for_domain(domain: str) -> str:
    return {
        "criminal": "형사 쟁점 검토",
        "civil": "민사 쟁점 검토",
        "labor": "노동 쟁점 검토",
        "administrative": "행정 쟁점 검토",
        "lease": "임대차 쟁점 검토",
    }[domain]


def _issue_query_for_domain(*, domain: str, facts: str, question: str) -> str:
    domain_terms = {
        "criminal": "형사 구성요건 책임능력 증거 입증 절차",
        "civil": "민사 계약 불법행위 손해배상 청구 입증",
        "labor": "근로기준법 임금 해고 산재 노동 분쟁",
        "administrative": "행정처분 인허가 제재 불복 행정소송",
        "lease": "임대차 보증금 대항력 갱신 명도 차임",
    }[domain]
    return f"{domain_terms}\n{facts}\n{question}".strip()


def _combined_query(
    *,
    facts: str,
    question: str,
    domain_tasks: list[dict[str, object]],
) -> str:
    issue_queries = [
        str(task.get("issue_query") or "").strip()
        for task in domain_tasks
        if str(task.get("issue_query") or "").strip()
    ]
    return "\n\n".join([facts.strip(), question.strip(), *issue_queries]).strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)
