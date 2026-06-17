"""도메인별 법률 쟁점 보고서를 만드는 전문 Agent입니다."""

from __future__ import annotations

from app.services.agent.contracts import (
    AgentContext,
    AgentHandoff,
    AgentName,
    AgentResult,
    AgentTask,
)


class CriminalLawAgent:
    """형사 도메인 쟁점 보고서를 작성합니다."""

    agent_name = "criminal_law"
    domain = "criminal"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        return _run_domain_agent(context, agent_name=self.agent_name, domain=self.domain)


class CivilLawAgent:
    """민사 도메인 쟁점 보고서를 작성합니다."""

    agent_name = "civil_law"
    domain = "civil"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        return _run_domain_agent(context, agent_name=self.agent_name, domain=self.domain)


class LaborLawAgent:
    """노동 도메인 쟁점 보고서를 작성합니다."""

    agent_name = "labor_law"
    domain = "labor"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        return _run_domain_agent(context, agent_name=self.agent_name, domain=self.domain)


class AdministrativeLawAgent:
    """행정 도메인 쟁점 보고서를 작성합니다."""

    agent_name = "administrative_law"
    domain = "administrative"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        return _run_domain_agent(context, agent_name=self.agent_name, domain=self.domain)


class LeaseLawAgent:
    """임대차 도메인 쟁점 보고서를 작성합니다."""

    agent_name = "lease_law"
    domain = "lease"

    def run(self, context: AgentContext, task: AgentTask) -> AgentResult:
        return _run_domain_agent(context, agent_name=self.agent_name, domain=self.domain)


def _run_domain_agent(
    context: AgentContext,
    *,
    agent_name: AgentName,
    domain: str,
) -> AgentResult:
    domain_task = _domain_task_for_agent(context, agent_name)
    if domain_task is None:
        return AgentResult(
            agent_name=agent_name,
            status="failed",
            output={"reason": "domain_task_missing"},
            error_code="domain_task_missing",
            error_message=f"Domain task was not planned for {agent_name}",
        )

    evidence_items = _evidence_for_domain(context.evidence_items, domain=domain)
    citations = _citations_for_evidence(context.citations, evidence_items)
    report = {
        "domain": domain,
        "agent_name": agent_name,
        "title": domain_task.get("title") or _domain_title(domain),
        "facts_slice": domain_task.get("facts_slice") or context.request.facts,
        "issue_query": domain_task.get("issue_query") or "",
        "issues": _default_issues_for_domain(domain),
        "evidence_chunk_ids": [
            item.get("chunk_id")
            for item in evidence_items
            if isinstance(item.get("chunk_id"), int)
        ],
        "citation_count": len(citations),
        "missing_facts": _missing_facts_for_domain(domain),
        "limitations": [
            "도메인 전문 Agent의 1차 보고이며 최종 판단은 synthesis 단계에서 통합합니다."
        ],
        "confidence": 0.65 if evidence_items else 0.45,
    }
    context.domain_reports.append(report)
    next_agent = _next_domain_agent(context, agent_name)

    return AgentResult(
        agent_name=agent_name,
        status="completed",
        output={
            "domain": domain,
            "evidence_count": len(evidence_items),
            "citation_count": len(citations),
            "report_index": len(context.domain_reports) - 1,
        },
        handoff=AgentHandoff(
            next_agent=next_agent or "evidence_verifier",
            reason="domain_report_completed",
            payload={"domain": domain},
        ),
        confidence=report["confidence"],
        requires_human_review=not bool(evidence_items),
    )


def _domain_task_for_agent(
    context: AgentContext,
    agent_name: AgentName,
) -> dict[str, object] | None:
    for domain_task in context.domain_tasks:
        if domain_task.get("agent_name") == agent_name:
            return domain_task
    return None


def _next_domain_agent(
    context: AgentContext,
    agent_name: AgentName,
) -> AgentName | None:
    domain_agents = [
        task.get("agent_name")
        for task in context.domain_tasks
        if isinstance(task.get("agent_name"), str)
    ]
    for index, planned_agent_name in enumerate(domain_agents):
        if planned_agent_name != agent_name:
            continue
        if index + 1 >= len(domain_agents):
            return None
        return domain_agents[index + 1]  # type: ignore[return-value]
    return None


def _evidence_for_domain(
    evidence_items: list[dict[str, object]],
    *,
    domain: str,
) -> list[dict[str, object]]:
    matched = [
        item
        for item in evidence_items
        if _metadata_contains_domain(item.get("metadata"), domain=domain)
    ]
    return matched or evidence_items


def _metadata_contains_domain(value: object, *, domain: str) -> bool:
    if not isinstance(value, dict):
        return False
    domain_tags = value.get("domain_tags")
    if isinstance(domain_tags, list) and domain in domain_tags:
        return True
    planned_domain = value.get("planned_issue_domain")
    return planned_domain == domain


def _citations_for_evidence(
    citations: list[dict[str, object]],
    evidence_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    chunk_ids = {
        item.get("chunk_id")
        for item in evidence_items
        if isinstance(item.get("chunk_id"), int)
    }
    return [
        citation
        for citation in citations
        if citation.get("chunk_id") in chunk_ids
    ]


def _default_issues_for_domain(domain: str) -> list[str]:
    return {
        "criminal": ["범죄 성립요건", "책임능력과 고의/과실", "증거와 입증", "절차상 쟁점"],
        "civil": ["청구권 근거", "손해 및 인과관계", "항변 가능성", "입증자료"],
        "labor": ["근로관계 성격", "임금/해고/산재 쟁점", "구제절차", "입증자료"],
        "administrative": ["처분성", "위법사유", "불복기간과 절차", "집행정지 가능성"],
        "lease": ["임대차 관계", "보증금/차임", "대항력과 우선변제", "명도 또는 반환 절차"],
    }[domain]


def _missing_facts_for_domain(domain: str) -> list[str]:
    return {
        "criminal": ["행위 당시 인식과 의사", "객관 증거", "수사 진행 단계"],
        "civil": ["계약서 또는 거래자료", "손해액 산정자료", "상대방 항변"],
        "labor": ["근로계약서", "임금명세서", "해고 또는 징계 경위"],
        "administrative": ["처분서", "통지일", "관련 행정기록"],
        "lease": ["임대차계약서", "보증금 지급자료", "목적물 인도와 점유 상태"],
    }[domain]


def _domain_title(domain: str) -> str:
    return {
        "criminal": "형사 쟁점 검토",
        "civil": "민사 쟁점 검토",
        "labor": "노동 쟁점 검토",
        "administrative": "행정 쟁점 검토",
        "lease": "임대차 쟁점 검토",
    }[domain]
