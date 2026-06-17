"""LLM-based legal source planning for official corpus enrichment."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from app.core.config import Settings
from app.services.ai.errors import ProviderError
from app.services.ai.types import AITextRequest

SUPPORTED_DOCUMENT_TYPES = {"statute"}
KNOWN_STATUTE_TITLES = (
    "주택임대차보호법",
    "상가건물 임대차보호법",
    "민법",
    "형법",
    "근로기준법",
    "산업재해보상보험법",
    "개인정보 보호법",
    "행정절차법",
    "행정소송법",
    "국가배상법",
    "민사소송법",
    "민사집행법",
    "형사소송법",
    "유사수신행위의 규제에 관한 법률",
    "자본시장과 금융투자업에 관한 법률",
    "이자제한법",
    "전자상거래 등에서의 소비자보호에 관한 법률",
    "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
)


@dataclass(frozen=True)
class LegalSourceCandidate:
    """공식 법령 API 조회에 사용할 검증된 후보입니다."""

    document_type: str
    title: str
    query: str
    reason: str | None = None


@dataclass(frozen=True)
class ExpectedArticleRef:
    """Planner/reviewer article hint; not citation evidence by itself."""

    law_title: str
    article_no: str
    article_title: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PlannedLegalIssue:
    """Single legal issue used as a retrieval unit before vector search."""

    issue_key: str
    title: str
    description: str | None
    internal_rag_query: str
    domain: str | None = None
    facts_slice: str | None = None
    official_source_query: str | None = None
    candidates: list[LegalSourceCandidate] = field(default_factory=list)
    expected_article_refs: list[ExpectedArticleRef] = field(default_factory=list)


@dataclass(frozen=True)
class LegalSourcePlan:
    """LLM 후보 추출 결과와 원문 응답을 함께 보관합니다."""

    candidates: list[LegalSourceCandidate] = field(default_factory=list)
    issues: list[PlannedLegalIssue] = field(default_factory=list)
    raw_text: str | None = None


class LegalSourcePlanningClient:
    def generate_text(self, request: AITextRequest):  # pragma: no cover - Protocol 대체
        raise NotImplementedError


def plan_legal_source_candidates(
    *,
    ai_client: LegalSourcePlanningClient,
    settings: Settings,
    facts: str,
    question: str,
    search_mode: str,
    max_candidates: int | None = None,
) -> LegalSourcePlan:
    """사용자 표현에서 공식 법령 조회 후보를 LLM으로 추출합니다."""

    candidate_limit = max_candidates or settings.ai_source_planner_max_candidates
    if candidate_limit <= 0:
        raise ValueError("max_candidates must be positive")

    model_name = settings.source_planner_model_name
    if not model_name or not hasattr(ai_client, "generate_text"):
        return _augment_plan_with_required_issue_hints(
            _fallback_plan(facts, question, limit=candidate_limit),
            facts=facts,
            question=question,
            limit=candidate_limit,
        )

    prompt = _build_planner_prompt(
        facts=facts,
        question=question,
        search_mode=search_mode,
        max_candidates=candidate_limit,
    )
    try:
        result = ai_client.generate_text(
            AITextRequest(
                prompt=prompt,
                model=model_name,
                temperature=0,
                timeout_seconds=settings.ai_request_timeout_seconds,
                metadata={"purpose": "legal_source_planner"},
            )
        )
    except ProviderError:
        return _augment_plan_with_required_issue_hints(
            _fallback_plan(facts, question, limit=candidate_limit),
            facts=facts,
            question=question,
            limit=candidate_limit,
        )
    plan = _parse_plan(result.text, limit=candidate_limit)
    if not plan.candidates and not plan.issues:
        fallback = _fallback_plan(facts, question, limit=candidate_limit)
        return _augment_plan_with_required_issue_hints(
            LegalSourcePlan(
                candidates=fallback.candidates,
                issues=fallback.issues,
                raw_text=result.text,
            ),
            facts=facts,
            question=question,
            limit=candidate_limit,
        )
    return _augment_plan_with_required_issue_hints(
        LegalSourcePlan(
            candidates=plan.candidates,
            issues=plan.issues,
            raw_text=result.text,
        ),
        facts=facts,
        question=question,
        limit=candidate_limit,
    )


def _build_planner_prompt(
    *,
    facts: str,
    question: str,
    search_mode: str,
    max_candidates: int,
) -> str:
    example = {
        "issues": [
            {
                "issue_key": "lease_deposit_return",
                "title": "lease deposit return",
                "description": "deposit return dispute",
                "domain": "lease",
                "facts_slice": "The lease ended but the landlord refuses to return the deposit.",
                "internal_rag_query": "lease deposit return statute",
                "official_source_query": "Residential Lease Protection Act",
                "expected_article_refs": [
                    {
                        "law_title": "Residential Lease Protection Act",
                        "article_no": "Article 3-2",
                        "article_title": "deposit return",
                        "reason": "direct issue provision",
                    }
                ],
                "official_source_candidates": [
                    {
                        "document_type": "statute",
                        "title": "Residential Lease Protection Act",
                        "query": "Residential Lease Protection Act",
                        "reason": "deposit return issue",
                    }
                ],
            }
        ]
    }
    return (
        "You plan Korean legal issues and official source searches for RAG.\n"
        "Return only a JSON object. Do not include markdown.\n"
        "The plan is not a legal conclusion and must not be cited directly.\n"
        "One user matter can contain multiple legal domains such as criminal, "
        "civil, labor, administrative, lease, consumer, and family.\n"
        "Split materially different domains or fact clusters into separate issues.\n"
        "Each issue must have one internal_rag_query. top_k is applied per issue.\n"
        "Each issue should include domain and facts_slice when identifiable.\n"
        "Each official_source_candidates item must target an official statute search.\n"
        "For each issue, include expected_article_refs when specific statutes/articles "
        "must be checked before drafting.\n"
        f"Return at most {max_candidates} issues and source candidates.\n"
        f"Schema example:\n{json.dumps(example, ensure_ascii=False)}\n"
        "Prefer exact statute titles when possible. If unsure, include a concise "
        "Korean search query. For criminal facts, consider 형법 and 형사소송법.\n\n"
        f"search_mode: {search_mode}\n"
        f"facts:\n{facts.strip()}\n\n"
        f"question:\n{question.strip()}\n"
    )


def _parse_plan(text: str, *, limit: int) -> LegalSourcePlan:
    try:
        payload = json.loads(_extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return LegalSourcePlan()
    if not isinstance(payload, dict):
        return LegalSourcePlan()

    top_level_candidates = _candidates_from_payload_list(
        payload.get("candidates"),
        limit=limit,
    )
    issues = _issues_from_payload(payload.get("issues"), limit=limit)
    if not issues and top_level_candidates:
        issues = [_issue_from_candidates(top_level_candidates)]
    candidates = _dedupe_candidates(
        [
            candidate
            for issue in issues
            for candidate in issue.candidates
        ]
        + top_level_candidates,
        limit=limit,
    )
    return LegalSourcePlan(candidates=candidates, issues=issues)


def _parse_candidates(text: str, *, limit: int) -> list[LegalSourceCandidate]:
    return _parse_plan(text, limit=limit).candidates


def _candidates_from_payload_list(
    raw_candidates: object,
    *,
    limit: int,
) -> list[LegalSourceCandidate]:
    if not isinstance(raw_candidates, list):
        return []

    candidates = [
        candidate
        for item in raw_candidates
        if (candidate := _candidate_from_payload(item)) is not None
    ]
    return _dedupe_candidates(candidates, limit=limit)


def _issues_from_payload(
    raw_issues: object,
    *,
    limit: int,
) -> list[PlannedLegalIssue]:
    if not isinstance(raw_issues, list):
        return []

    issues: list[PlannedLegalIssue] = []
    seen: set[str] = set()
    for item in raw_issues:
        issue = _issue_from_payload(item, index=len(issues) + 1, limit=limit)
        if issue is None:
            continue
        if issue.issue_key in seen:
            issue = PlannedLegalIssue(
                issue_key=f"{issue.issue_key}_{len(issues) + 1}",
                title=issue.title,
                description=issue.description,
                internal_rag_query=issue.internal_rag_query,
                domain=issue.domain,
                facts_slice=issue.facts_slice,
                official_source_query=issue.official_source_query,
                candidates=issue.candidates,
                expected_article_refs=issue.expected_article_refs,
            )
        seen.add(issue.issue_key)
        issues.append(issue)
        if len(issues) >= limit:
            break
    return issues


def _issue_from_payload(
    value: object,
    *,
    index: int,
    limit: int,
) -> PlannedLegalIssue | None:
    if not isinstance(value, dict):
        return None

    candidates = _candidates_from_payload_list(
        value.get("official_source_candidates") or value.get("candidates"),
        limit=limit,
    )
    expected_article_refs = _article_refs_from_payload_list(
        value.get("expected_article_refs") or value.get("article_refs")
    )
    official_source_query = (
        _string_value(value.get("official_source_query"))
        or _string_value(value.get("external_source_query"))
    )
    if not candidates and official_source_query:
        candidates = [
            LegalSourceCandidate(
                document_type="statute",
                title=official_source_query,
                query=official_source_query,
                reason="issue_official_source_query",
            )
        ]

    title = (
        _string_value(value.get("title"))
        or _string_value(value.get("issue_title"))
        or official_source_query
        or (candidates[0].title if candidates else "")
    )
    internal_rag_query = (
        _string_value(value.get("internal_rag_query"))
        or _string_value(value.get("rag_query"))
        or _string_value(value.get("query"))
        or official_source_query
        or title
    )
    if not internal_rag_query:
        return None

    issue_key = (
        _string_value(value.get("issue_key"))
        or _string_value(value.get("key"))
        or _make_issue_key(title or internal_rag_query, index=index)
    )
    return PlannedLegalIssue(
        issue_key=issue_key,
        title=title or internal_rag_query,
        description=_string_value(value.get("description")),
        internal_rag_query=internal_rag_query,
        domain=_domain_from_payload(value),
        facts_slice=(
            _string_value(value.get("facts_slice"))
            or _string_value(value.get("fact_slice"))
            or _string_value(value.get("relevant_facts"))
        ),
        official_source_query=official_source_query,
        candidates=candidates,
        expected_article_refs=expected_article_refs,
    )


def _issue_from_candidates(
    candidates: list[LegalSourceCandidate],
) -> PlannedLegalIssue:
    query = " ".join(candidate.query for candidate in candidates)
    title = candidates[0].title if candidates else query
    return PlannedLegalIssue(
        issue_key=_make_issue_key(title or query, index=1),
        title=title or query,
        description=None,
        internal_rag_query=query,
        official_source_query=candidates[0].query if candidates else None,
        candidates=candidates,
    )


def _article_refs_from_payload_list(raw_refs: object) -> list[ExpectedArticleRef]:
    if not isinstance(raw_refs, list):
        return []
    refs = [
        article_ref
        for item in raw_refs
        if (article_ref := _article_ref_from_payload(item)) is not None
    ]
    return _dedupe_article_refs(refs)


def _article_ref_from_payload(value: object) -> ExpectedArticleRef | None:
    if not isinstance(value, dict):
        return None
    law_title = (
        _string_value(value.get("law_title"))
        or _string_value(value.get("statute_title"))
        or _string_value(value.get("title"))
    )
    article_no = (
        _string_value(value.get("article_no"))
        or _string_value(value.get("article"))
        or _string_value(value.get("article_number"))
    )
    if not law_title or not article_no:
        return None
    return ExpectedArticleRef(
        law_title=law_title,
        article_no=_normalize_article_no(article_no),
        article_title=_string_value(value.get("article_title")),
        reason=_string_value(value.get("reason")),
    )


def _dedupe_candidates(
    candidates: list[LegalSourceCandidate],
    *,
    limit: int,
) -> list[LegalSourceCandidate]:
    if limit <= 0:
        return []
    deduped: list[LegalSourceCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.document_type, _normalize_title(candidate.query))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= limit:
            break
    return deduped


def _legacy_parse_candidates(text: str, *, limit: int) -> list[LegalSourceCandidate]:
    try:
        payload = json.loads(_extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[LegalSourceCandidate] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_candidates:
        candidate = _candidate_from_payload(item)
        if candidate is None:
            continue
        key = (candidate.document_type, _normalize_title(candidate.query))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def _candidate_from_payload(value: object) -> LegalSourceCandidate | None:
    if not isinstance(value, dict):
        return None
    document_type = _string_value(value.get("document_type")) or "statute"
    if document_type not in SUPPORTED_DOCUMENT_TYPES:
        return None
    title = _string_value(value.get("title")) or ""
    query = _string_value(value.get("query")) or title
    if not query:
        return None
    reason = _string_value(value.get("reason"))
    return LegalSourceCandidate(
        document_type=document_type,
        title=title or query,
        query=query,
        reason=reason,
    )


def _fallback_candidates(
    facts: str,
    question: str,
    *,
    limit: int,
) -> list[LegalSourceCandidate]:
    text = f"{facts}\n{question}"
    candidates = [
        LegalSourceCandidate(
            document_type="statute",
            title=title,
            query=title,
            reason="explicit_or_known_statute_fallback",
        )
        for title in KNOWN_STATUTE_TITLES
        if _normalize_title(title) in _normalize_title(text)
    ]
    if candidates:
        return candidates[:limit]
    fallback_query = (question.strip() or facts.strip())[:200]
    if not fallback_query:
        return []
    return [
        LegalSourceCandidate(
            document_type="statute",
            title=fallback_query,
            query=fallback_query,
            reason="raw_query_fallback",
        )
    ]


def _fallback_plan(
    facts: str,
    question: str,
    *,
    limit: int,
) -> LegalSourcePlan:
    candidates = _fallback_candidates(facts, question, limit=limit)
    fallback_query = (question.strip() or facts.strip())[:200]
    if candidates:
        issue = _issue_from_candidates(candidates)
        if fallback_query:
            issue = PlannedLegalIssue(
                issue_key=issue.issue_key,
                title=issue.title,
                description=issue.description,
                internal_rag_query=f"{fallback_query} {issue.internal_rag_query}".strip(),
                domain=issue.domain,
                facts_slice=issue.facts_slice,
                official_source_query=issue.official_source_query,
                candidates=issue.candidates,
                expected_article_refs=issue.expected_article_refs,
            )
        return LegalSourcePlan(candidates=candidates, issues=[issue])
    if not fallback_query:
        return LegalSourcePlan()
    return LegalSourcePlan(
        issues=[
            PlannedLegalIssue(
                issue_key="issue_1",
                title=fallback_query,
                description=None,
                internal_rag_query=fallback_query,
                official_source_query=None,
                candidates=[],
            )
        ]
    )


def _augment_plan_with_required_issue_hints(
    plan: LegalSourcePlan,
    *,
    facts: str,
    question: str,
    limit: int,
) -> LegalSourcePlan:
    required_issues = [
        *_criminal_required_issues(facts=facts, question=question),
        *_investment_required_issues(facts=facts, question=question),
        *_mixed_domain_required_issues(facts=facts, question=question),
    ]
    if not required_issues:
        return plan

    # 사실관계에서 명백히 드러난 핵심 도메인 힌트는 외부 API 동기화 우선순위를
    # 가져야 합니다. LLM이 일반 사용자 표현을 잘못 해석해 엉뚱한 법령을 앞세워도
    # 필수 후보가 먼저 검색되도록 하되, 조문번호는 reviewer 검토 힌트로만 씁니다.
    merged_issues = _dedupe_issues([*required_issues, *plan.issues])
    merged_candidates = _dedupe_candidates(
        [
            candidate
            for issue in merged_issues
            for candidate in issue.candidates
        ]
        + plan.candidates,
        limit=limit,
    )
    return LegalSourcePlan(
        candidates=merged_candidates,
        issues=merged_issues,
        raw_text=plan.raw_text,
    )


def _criminal_required_issues(
    *,
    facts: str,
    question: str,
) -> list[PlannedLegalIssue]:
    text = f"{facts}\n{question}"
    normalized_text = _normalize_title(text)
    issues: list[PlannedLegalIssue] = []

    has_death_fact = any(
        keyword in normalized_text
        for keyword in ("죽", "사망", "시체", "시신", "사체", "살해")
    )
    has_accidental_fact = any(
        keyword in normalized_text
        for keyword in ("실수", "과실", "부주의", "잘못")
    )
    if has_death_fact and has_accidental_fact:
        issues.append(
            _required_issue(
                issue_key="criminal_negligent_death",
                title="과실 사망 결과",
                query="형법 제267조 과실치사 제14조 과실 사망 결과",
                refs=[
                    ExpectedArticleRef(
                        law_title="형법",
                        article_no="제267조",
                        article_title="과실치사",
                        reason="실수로 사람을 사망하게 한 최초 행위의 구성요건 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="형법",
                        article_no="제14조",
                        article_title="과실",
                        reason="과실범 처벌 가능성의 일반 원칙 확인",
                    ),
                ],
            )
        )

    has_corpse_fact = any(
        keyword in normalized_text for keyword in ("시체", "시신", "사체", "변사체")
    )
    has_concealment_fact = any(
        keyword in normalized_text
        for keyword in ("매장", "묻", "은닉", "숨", "비닐", "유기")
    )
    if has_corpse_fact and has_concealment_fact:
        issues.append(
            _required_issue(
                issue_key="criminal_corpse_concealment",
                title="사체 은닉 및 매장",
                query="형법 제161조 사체유기 시체 은닉 매장 제163조 변사체 검시 방해",
                refs=[
                    ExpectedArticleRef(
                        law_title="형법",
                        article_no="제161조",
                        article_title="사체등의 유기",
                        reason="시신을 옮기거나 매장한 행위의 별도 범죄 성립 가능성 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="형법",
                        article_no="제163조",
                        article_title="변사체 검시 방해",
                        reason="변사체 은닉으로 검시가 방해되는지 확인",
                    ),
                ],
            )
        )

    if "자수" in normalized_text or "경찰서" in normalized_text:
        issues.append(
            _required_issue(
                issue_key="criminal_self_surrender",
                title="자수와 감경",
                query="형법 제52조 자수 제53조 정상참작감경",
                refs=[
                    ExpectedArticleRef(
                        law_title="형법",
                        article_no="제52조",
                        article_title="자수ㆍ자복",
                        reason="경찰서에 자진 신고한 행위의 감경 가능성 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="형법",
                        article_no="제53조",
                        article_title="정상참작감경",
                        reason="자수 외 양형상 정상참작 가능성 확인",
                    ),
                ],
            )
        )

    if has_corpse_fact and any(
        keyword in normalized_text for keyword in ("찾지못", "수색", "장소", "발굴")
    ):
        issues.append(
            _required_issue(
                issue_key="criminal_procedure_body_search",
                title="시신 미발견 상태의 수사상 처분",
                query="형사소송법 제140조 검증 필요한 처분 사체 해부 분묘 발굴",
                refs=[
                    ExpectedArticleRef(
                        law_title="형사소송법",
                        article_no="제140조",
                        article_title="검증과 필요한 처분",
                        reason="시신 위치 특정과 발굴 등 수사상 처분 가능성 확인",
                    )
                ],
            )
        )

    return issues


def _investment_required_issues(
    *,
    facts: str,
    question: str,
) -> list[PlannedLegalIssue]:
    text = f"{facts}\n{question}"
    normalized_text = _normalize_title(text)
    issues: list[PlannedLegalIssue] = []

    has_investment_fact = any(
        keyword in normalized_text
        for keyword in ("투자", "수익률", "수익", "원금", "보장", "투자처")
    )
    has_money_delivery = any(
        keyword in normalized_text
        for keyword in ("받", "지급", "돌려", "반환", "상환", "정산", "보수")
    )
    has_high_yield_or_guarantee = any(
        keyword in normalized_text
        for keyword in ("50%", "50퍼센트", "고수익", "수익률", "보장")
    )
    has_fraud_signal = any(
        keyword in normalized_text for keyword in ("편취", "달아", "기망", "속", "사기")
    )

    if has_investment_fact and has_money_delivery:
        issues.append(
            _required_issue(
                issue_key="civil_contract_breach_investment",
                title="투자 약정과 채무불이행",
                query=(
                    "민법 채무불이행 손해배상 계약 해석 임의규정 "
                    "신의성실 투자금 반환 정산"
                ),
                refs=[
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제390조",
                        article_title="채무불이행과 손해배상",
                        reason="투자 약정 위반 또는 반환의무 불이행 여부 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제393조",
                        article_title="손해배상의 범위",
                        reason="계약 위반 시 통상손해와 특별손해 범위 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제105조",
                        article_title="임의규정",
                        reason="당사자 약정이 민법 임의규정보다 우선되는지 확인",
                    ),
                ],
                domain="civil",
            )
        )
        issues.append(
            _required_issue(
                issue_key="civil_mandate_accounting_investment",
                title="투자 운용 위임과 정산",
                query=(
                    "민법 위임 수임인 선관주의 보고의무 취득물 인도 "
                    "보수청구 투자 운용 정산"
                ),
                refs=[
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제681조",
                        article_title="수임인의 선관의무",
                        reason="A가 투자 운용을 맡은 경우 주의의무 위반 여부 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제683조",
                        article_title="수임인의 보고의무",
                        reason="운용 경과와 손익 정산 설명의무 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제684조",
                        article_title="수임인의 취득물 등의 인도ㆍ이전의무",
                        reason="투자 운용으로 취득한 금전의 귀속과 인도의무 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제686조",
                        article_title="수임인의 보수청구권",
                        reason="A가 500만원을 보수로 공제할 수 있는지 확인",
                    ),
                ],
                domain="civil",
            )
        )

    if has_investment_fact and (has_high_yield_or_guarantee or has_fraud_signal):
        issues.append(
            _required_issue(
                issue_key="criminal_fraud_investment",
                title="투자금 편취와 사기 가능성",
                query="형법 사기 기망 투자금 편취 수익률 보장 투자처 설명",
                refs=[
                    ExpectedArticleRef(
                        law_title="형법",
                        article_no="제347조",
                        article_title="사기",
                        reason="수익률 보장 설명이 기망에 해당하는지 확인",
                    )
                ],
                domain="criminal",
            )
        )

    if has_investment_fact and has_high_yield_or_guarantee:
        issues.append(
            _required_issue(
                issue_key="financial_regulation_guaranteed_return",
                title="수익 보장 투자 모집의 금융규제",
                query=(
                    "유사수신행위 규제 원금 초과 수익 보장 자본시장법 "
                    "손실보전 이익보장 이자제한 투자 권유"
                ),
                refs=[
                    ExpectedArticleRef(
                        law_title="유사수신행위의 규제에 관한 법률",
                        article_no="제3조",
                        article_title="유사수신행위의 금지",
                        reason="원금 또는 수익 보장 방식의 자금 조달 금지 여부 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="자본시장과 금융투자업에 관한 법률",
                        article_no="제55조",
                        article_title="손실보전 등의 금지",
                        reason="투자 권유 과정에서 이익 보장 약정이 제한되는지 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="이자제한법",
                        article_no="제2조",
                        article_title="이자의 최고한도",
                        reason="거래가 금전대차로 평가될 경우 고율 수익 약정 제한 확인",
                    ),
                ],
                domain="financial_regulation",
            )
        )

    return issues


def _mixed_domain_required_issues(
    *,
    facts: str,
    question: str,
) -> list[PlannedLegalIssue]:
    text = f"{facts}\n{question}"
    normalized_text = _normalize_title(text)
    issues: list[PlannedLegalIssue] = []

    if any(keyword in normalized_text for keyword in ("임대차", "보증금", "월세")):
        issues.append(
            _required_issue(
                issue_key="lease_contract_return",
                title="임대차 보증금 및 계약상 정산",
                query="주택임대차보호법 민법 임대차 보증금 반환 수리비 공제",
                refs=[
                    ExpectedArticleRef(
                        law_title="주택임대차보호법",
                        article_no="제3조의2",
                        article_title="보증금의 회수",
                        reason="임대차 종료 후 보증금 회수 쟁점 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="민법",
                        article_no="제623조",
                        article_title="임대인의 의무",
                        reason="임대 목적물 유지ㆍ수선 관련 기본 의무 확인",
                    ),
                ],
                domain="lease",
            )
        )
    if any(keyword in normalized_text for keyword in ("임금", "해고", "산재", "근로")):
        issues.append(
            _source_only_issue(
                issue_key="labor_wage_dismissal_accident",
                title="노동관계 임금ㆍ해고ㆍ산재",
                query="근로기준법 산업재해보상보험법 임금체불 부당해고 산재",
                law_titles=["근로기준법", "산업재해보상보험법"],
                domain="labor",
            )
        )
    if any(keyword in normalized_text for keyword in ("영업정지", "처분", "행정")):
        issues.append(
            _required_issue(
                issue_key="administrative_disposition_remedy",
                title="행정처분과 불복",
                query="행정절차법 행정소송법 영업정지 처분 불복 집행정지",
                refs=[
                    ExpectedArticleRef(
                        law_title="행정절차법",
                        article_no="제21조",
                        article_title="처분의 사전 통지",
                        reason="불이익 처분 전 사전 통지 여부 확인",
                    ),
                    ExpectedArticleRef(
                        law_title="행정소송법",
                        article_no="제23조",
                        article_title="집행정지",
                        reason="영업정지 처분의 효력정지 가능성 확인",
                    ),
                ],
                domain="administrative",
            )
        )
    if any(keyword in normalized_text for keyword in ("개인정보", "신상", "공개")):
        issues.append(
            _source_only_issue(
                issue_key="privacy_disclosure",
                title="개인정보 공개와 손해",
                query="개인정보 보호법 국가배상법 개인정보 공개 손해배상",
                law_titles=["개인정보 보호법", "국가배상법"],
                domain="privacy",
            )
        )
    if any(keyword in normalized_text for keyword in ("중고", "환불", "전자상거래")):
        issues.append(
            _source_only_issue(
                issue_key="consumer_refund_fraud",
                title="소비자 거래와 환불",
                query="민법 전자상거래 소비자보호법 환불 하자 사기",
                law_titles=["민법", "전자상거래 등에서의 소비자보호에 관한 법률"],
                domain="consumer",
            )
        )
    if any(keyword in normalized_text for keyword in ("명예훼손", "게시글", "댓글")):
        issues.append(
            _source_only_issue(
                issue_key="online_defamation",
                title="온라인 명예훼손",
                query="형법 정보통신망법 명예훼손 게시글 댓글",
                law_titles=["형법", "정보통신망 이용촉진 및 정보보호 등에 관한 법률"],
                domain="criminal",
            )
        )
    if any(keyword in normalized_text for keyword in ("상속", "유류분", "상속재산")):
        issues.append(
            _source_only_issue(
                issue_key="inheritance_property_dispute",
                title="상속재산과 권리관계",
                query="민법 상속재산 유류분 임대차 대여금",
                law_titles=["민법"],
                domain="family_civil",
            )
        )
    return issues


def _required_issue(
    *,
    issue_key: str,
    title: str,
    query: str,
    refs: list[ExpectedArticleRef],
    domain: str = "criminal",
) -> PlannedLegalIssue:
    candidates = _dedupe_candidates(
        [
            LegalSourceCandidate(
                document_type="statute",
                title=ref.law_title,
                query=ref.law_title,
                reason="required_issue_hint",
            )
            for ref in refs
        ],
        limit=len(refs),
    )
    return PlannedLegalIssue(
        issue_key=issue_key,
        title=title,
        description="사실관계상 누락되면 안 되는 핵심 쟁점 검색 힌트입니다.",
        internal_rag_query=_strip_article_numbers(query),
        domain=domain,
        official_source_query=candidates[0].query if candidates else None,
        candidates=candidates,
        expected_article_refs=refs,
    )


def _source_only_issue(
    *,
    issue_key: str,
    title: str,
    query: str,
    law_titles: list[str],
    domain: str,
) -> PlannedLegalIssue:
    candidates = _dedupe_candidates(
        [
            LegalSourceCandidate(
                document_type="statute",
                title=law_title,
                query=law_title,
                reason="domain_source_hint",
            )
            for law_title in law_titles
        ],
        limit=len(law_titles),
    )
    return PlannedLegalIssue(
        issue_key=issue_key,
        title=title,
        description="복수 법률영역 사건에서 누락되면 안 되는 공식 법령 후보입니다.",
        internal_rag_query=query,
        domain=domain,
        official_source_query=candidates[0].query if candidates else None,
        candidates=candidates,
        expected_article_refs=[],
    )


def _dedupe_issues(issues: list[PlannedLegalIssue]) -> list[PlannedLegalIssue]:
    deduped: list[PlannedLegalIssue] = []
    seen_keys: set[str] = set()
    seen_article_refs: set[tuple[str, str]] = set()
    for issue in issues:
        article_refs = _dedupe_article_refs(issue.expected_article_refs)
        new_refs = [
            ref
            for ref in article_refs
            if (_article_ref_key(ref) not in seen_article_refs)
        ]
        if issue.issue_key in seen_keys and not new_refs:
            continue
        seen_keys.add(issue.issue_key)
        for ref in article_refs:
            seen_article_refs.add(_article_ref_key(ref))
        deduped.append(
            PlannedLegalIssue(
                issue_key=issue.issue_key,
                title=issue.title,
                description=issue.description,
                internal_rag_query=issue.internal_rag_query,
                domain=issue.domain,
                facts_slice=issue.facts_slice,
                official_source_query=issue.official_source_query,
                candidates=issue.candidates,
                expected_article_refs=article_refs,
            )
        )
    return deduped


def _dedupe_article_refs(refs: list[ExpectedArticleRef]) -> list[ExpectedArticleRef]:
    deduped: list[ExpectedArticleRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = _article_ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _article_ref_key(ref: ExpectedArticleRef) -> tuple[str, str]:
    return (_normalize_title(ref.law_title), _normalize_article_no(ref.article_no))


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("JSON object was not found")
    return stripped[start : end + 1]


def _domain_from_payload(value: dict[str, object]) -> str | None:
    domain = (
        _string_value(value.get("domain"))
        or _string_value(value.get("legal_domain"))
        or _string_value(value.get("category"))
    )
    if domain:
        return domain
    raw_domains = value.get("domains") or value.get("legal_domains")
    if not isinstance(raw_domains, list):
        return None
    for raw_domain in raw_domains:
        domain = _string_value(raw_domain)
        if domain:
            return domain
    return None


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _normalize_article_no(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _strip_article_numbers(value: str) -> str:
    stripped = re.sub(r"제\s*\d+\s*조(?:의\s*\d+)?", "", value)
    return re.sub(r"\s+", " ", stripped).strip()


def _make_issue_key(value: str, *, index: int) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip().lower()).strip("_")
    return normalized[:80] or f"issue_{index}"
