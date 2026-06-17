from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from typing import Any, Literal, TypedDict

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.ai import AgentStep, EditorAgentHistoryMessage, EditorAgentResponse, ExternalResource, RagCitation, ToolLog
from app.services.ai_runtime import _extract_json, _extract_query_noun_terms, _generate_text, search_external, search_rag
from app.services.safety import editor_response_from_safety, moderate_input

EditorAction = Literal["answer", "fill_content", "revise_content"]

KING_NAMES = [
    "태조",
    "정종",
    "태종",
    "세종",
    "문종",
    "단종",
    "세조",
    "예종",
    "성종",
    "연산군",
    "중종",
    "인종",
    "명종",
    "선조",
    "광해군",
    "인조",
    "효종",
    "현종",
    "숙종",
    "경종",
    "영조",
    "정조",
    "순조",
    "헌종",
    "철종",
    "고종",
    "순종",
    "양녕대군",
    "효령대군",
    "충녕대군",
]
SOURCE_KEYWORDS = ["어찰", "편지", "서찰", "문서", "일기", "실록", "사료", "원문", "국역"]
EDITOR_AGENT_PROGRESS_STEPS = [
    {"step": "safety", "label": "요청 안전성 확인", "percent": 8},
    {"step": "intent", "label": "요청 의도 분석", "percent": 18},
    {"step": "plan", "label": "답변 계획 수립", "percent": 32},
    {"step": "retrieve", "label": "RAG 근거 검색", "percent": 48},
    {"step": "external_search", "label": "외부 자료 확인", "percent": 64},
    {"step": "evidence", "label": "근거 정리", "percent": 78},
    {"step": "respond", "label": "답변 구성", "percent": 92},
]


class EditorAgentState(TypedDict, total=False):
    title: str
    content: str
    post_type: str
    category: str
    message: str
    history: list[dict[str, str]]
    action: EditorAction
    rag_query: str
    answer_plan: dict[str, object]
    evidence_summary: str | None
    citations: list[RagCitation]
    external_resources: list[ExternalResource]
    evidence_claims: list[dict[str, str]]
    coverage_report: dict[str, object]
    tool_logs: list[ToolLog]
    weak_evidence: bool
    agent_steps: list[AgentStep]
    response: EditorAgentResponse
    graph_mode: str


class QualityReview(TypedDict):
    passed: bool
    score: float
    issues: list[str]
    revision_instruction: str


def run_editor_agent(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    post_type: str,
    category: str,
    message: str,
    history: list[EditorAgentHistoryMessage] | None = None,
) -> EditorAgentResponse:
    safety_response = editor_response_from_safety(moderate_input(message, surface="editor", require_history_topic=False))
    if safety_response is not None:
        return safety_response
    topic_check_text = "\n".join([message, title, content])
    safety_response = editor_response_from_safety(moderate_input(topic_check_text, surface="editor"))
    if safety_response is not None:
        return safety_response

    initial_state: EditorAgentState = {
        "title": title.strip(),
        "content": content.strip(),
        "post_type": post_type,
        "category": category.strip(),
        "message": message.strip(),
        "history": [
            {"role": item.role, "content": item.content.strip()}
            for item in (history or [])[-8:]
            if item.content.strip()
        ],
        "agent_steps": [],
        "graph_mode": "langgraph",
    }

    try:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(EditorAgentState)
        graph.add_node("intent", _intent_node)
        graph.add_node("plan", lambda state: _plan_node(state, settings))
        graph.add_node("retrieve", lambda state: _retrieve_node(state, db, settings))
        graph.add_node("external_search", lambda state: _external_search_node(state, db, settings))
        graph.add_node("evidence", lambda state: _evidence_node(state, settings))
        graph.add_node("respond", lambda state: _respond_node(state, settings))
        graph.set_entry_point("intent")
        graph.add_edge("intent", "plan")
        graph.add_edge("plan", "retrieve")
        graph.add_edge("retrieve", "external_search")
        graph.add_edge("external_search", "evidence")
        graph.add_edge("evidence", "respond")
        graph.add_edge("respond", END)
        result = graph.compile().invoke(initial_state)
    except ImportError:
        fallback_state: EditorAgentState = {**initial_state, "graph_mode": "local_fallback"}
        intended = {**fallback_state, **_intent_node(fallback_state)}
        planned = {**intended, **_plan_node(intended, settings)}
        retrieved = {**planned, **_retrieve_node(planned, db, settings)}
        external = {**retrieved, **_external_search_node(retrieved, db, settings)}
        evidenced = {**external, **_evidence_node(external, settings)}
        result = {**evidenced, **_respond_node(evidenced, settings)}

    return result["response"]


def run_editor_agent_stream(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    post_type: str,
    category: str,
    message: str,
    history: list[EditorAgentHistoryMessage] | None = None,
) -> Iterator[dict[str, Any]]:
    yield _editor_agent_progress_event("safety")
    safety_response = editor_response_from_safety(moderate_input(message, surface="editor", require_history_topic=False))
    if safety_response is not None:
        yield {"type": "done", "response": safety_response}
        return

    topic_check_text = "\n".join([message, title, content])
    safety_response = editor_response_from_safety(moderate_input(topic_check_text, surface="editor"))
    if safety_response is not None:
        yield {"type": "done", "response": safety_response}
        return

    state: EditorAgentState = {
        "title": title.strip(),
        "content": content.strip(),
        "post_type": post_type,
        "category": category.strip(),
        "message": message.strip(),
        "history": [
            {"role": item.role, "content": item.content.strip()}
            for item in (history or [])[-8:]
            if item.content.strip()
        ],
        "agent_steps": [],
        "graph_mode": "stream",
    }

    yield _editor_agent_progress_event("intent")
    state = {**state, **_intent_node(state)}
    yield _editor_agent_progress_event("plan")
    state = {**state, **_plan_node(state, settings)}
    yield _editor_agent_progress_event("retrieve")
    state = {**state, **_retrieve_node(state, db, settings)}
    yield _editor_agent_progress_event("external_search")
    state = {**state, **_external_search_node(state, db, settings)}
    yield _editor_agent_progress_event("evidence")
    state = {**state, **_evidence_node(state, settings)}
    yield _editor_agent_progress_event("respond")
    state = {**state, **_respond_node(state, settings)}
    yield {"type": "done", "response": state["response"]}


def _editor_agent_progress_event(step: str) -> dict[str, Any]:
    progress = next(item for item in EDITOR_AGENT_PROGRESS_STEPS if item["step"] == step)
    return {"type": "progress", **progress}


def _intent_node(state: EditorAgentState) -> EditorAgentState:
    action = _classify_action(state["message"])
    rag_query = _build_rag_query(state)
    action_label = {
        "answer": "질문 답변",
        "fill_content": "본문 생성",
        "revise_content": "본문 수정",
    }[action]
    return {
        "action": action,
        "rag_query": rag_query,
        "agent_steps": [
            *state.get("agent_steps", []),
            AgentStep(name="intent", output=f"사용자 메시지를 `{action_label}` 요청으로 분류했습니다."),
        ],
    }


def _plan_node(state: EditorAgentState, settings: Settings) -> EditorAgentState:
    plan = _make_answer_plan(state, settings)
    return {
        "answer_plan": plan,
    }


def _retrieve_node(
    state: EditorAgentState,
    db: Session,
    settings: Settings,
) -> EditorAgentState:
    query = state.get("rag_query", "").strip()
    if not query:
        return {
            "evidence_summary": None,
            "citations": [],
            "weak_evidence": True,
            "agent_steps": [
                *state.get("agent_steps", []),
                AgentStep(name="rag.search", output="검색할 질문이나 초안 내용이 부족해 RAG 조회를 건너뛰었습니다."),
            ],
        }

    result = search_rag(db, settings, query, 2)
    titles = ", ".join(citation.title for citation in result.citations[:2]) or "없음"
    return {
        "evidence_summary": result.answer_summary,
        "citations": result.citations,
        "weak_evidence": result.weak_evidence,
        "agent_steps": [
            *state.get("agent_steps", []),
            AgentStep(
                name="rag.search",
                output=f"관련 내부 RAG 근거 {len(result.citations)}건을 조회했습니다. 근거: {titles}",
            ),
        ],
    }


def _external_search_node(state: EditorAgentState, db: Session, settings: Settings) -> EditorAgentState:
    if not _needs_external_search(state):
        return {
            "external_resources": [],
            "tool_logs": [],
            "agent_steps": [
                *state.get("agent_steps", []),
                AgentStep(name="external.search", output="내부 RAG 근거가 충분해 외부 검색을 건너뛰었습니다."),
            ],
        }

    keywords = _planned_external_keywords(state)
    resources: list[ExternalResource] = []
    tool_logs: list[ToolLog] = []
    seen_urls: set[str] = set()
    search_settings = settings.model_copy(update={"openai_api_key": None}) if settings.openai_api_key else settings
    with ThreadPoolExecutor(max_workers=max(1, len(keywords))) as executor:
        results = list(executor.map(lambda keyword: search_external(None, keyword, search_settings), keywords))
    for result in results:
        tool_logs.append(result.tool_log)
        for resource in result.resources:
            if resource.url in seen_urls:
                continue
            seen_urls.add(resource.url)
            resources.append(resource)
    has_primary = any(resource.verification_status == "primary_verified" for resource in resources)
    return {
        "external_resources": resources[:12],
        "tool_logs": tool_logs,
        "weak_evidence": False if has_primary else state.get("weak_evidence", True),
        "agent_steps": [
            *state.get("agent_steps", []),
            AgentStep(
                name="external.search",
                output=(
                    f"계획 기반 외부 자료 검색 {len(keywords)}회를 실행했습니다. "
                    f"확인 리소스 {len(resources[:12])}건."
                ),
            ),
        ],
    }


def _evidence_node(state: EditorAgentState, settings: Settings) -> EditorAgentState:
    claims = _extract_evidence_claims(state, settings)
    coverage = _check_plan_coverage(state, claims, settings)
    covered = coverage.get("covered", [])
    missing = coverage.get("missing", [])
    return {
        "evidence_claims": claims,
        "coverage_report": coverage,
        "agent_steps": [
            *state.get("agent_steps", []),
            AgentStep(
                name="evidence.claims",
                output=f"검색 근거에서 claim {len(claims)}개를 추출했습니다.",
            ),
            AgentStep(
                name="coverage.check",
                output=f"계획 질문 반영 상태: 확인 {len(covered)}개, 부족 {len(missing)}개.",
            ),
        ],
    }


def _respond_node(state: EditorAgentState, settings: Settings) -> EditorAgentState:
    if settings.openai_api_key:
        response = _make_llm_response(state, settings)
    else:
        response = _make_local_response(state)

    if state.get("graph_mode") == "langgraph":
        graph_output = "LangGraph 노드 흐름으로 응답을 생성했습니다."
    elif state.get("graph_mode") == "stream":
        graph_output = "스트리밍 노드 흐름으로 응답을 생성했습니다."
    else:
        graph_output = "LangGraph 패키지가 없는 환경이라 같은 순서를 로컬 fallback으로 처리했습니다."
    response, quality_steps = _quality_gate_response(state, response, settings)
    return {
        "response": response.model_copy(
            update={
                "agent_steps": [
                    *state.get("agent_steps", []),
                    AgentStep(name="respond", output=graph_output),
                    *quality_steps,
                ],
                "evidence_summary": state.get("evidence_summary"),
                "external_resources": state.get("external_resources", []),
                "tool_logs": state.get("tool_logs", []),
                "weak_evidence": bool(state.get("weak_evidence", False)),
            }
        )
    }


def _classify_action(message: str) -> EditorAction:
    normalized = message.replace(" ", "")
    fill_terms = [
        "본문채워",
        "본문써",
        "글써",
        "작성해",
        "써줘",
        "써주세요",
        "초안",
        "분량",
        "800자",
        "길게",
        "게시물",
        "게시글",
        "포스트",
    ]
    revise_terms = ["다듬", "수정", "고쳐", "바꿔", "늘려", "줄여", "개선"]
    if any(term in normalized for term in revise_terms) and stateful_content_hint(normalized):
        return "revise_content"
    if any(term in normalized for term in fill_terms):
        return "fill_content"
    return "answer"


def stateful_content_hint(normalized_message: str) -> bool:
    return any(term in normalized_message for term in ["본문", "글", "초안", "문장", "게시물", "게시글"])


def _needs_external_search(state: EditorAgentState) -> bool:
    if state.get("action") == "answer":
        return True
    return bool(state.get("weak_evidence", False)) or not state.get("citations")


def _external_keyword(state: EditorAgentState) -> str:
    text = " ".join(
        part
        for part in [
            state.get("title", ""),
            state.get("content", "")[:300],
            state["message"],
        ]
        if part
    )
    focused_keyword = _focused_external_keyword(text)
    if focused_keyword:
        return focused_keyword

    candidates = _extract_query_noun_terms(text)
    if candidates:
        return " ".join(candidates[:4])[:80]
    return (state.get("title") or state["message"])[:40]


def _focused_external_keyword(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip()
    person = next((name for name in sorted(KING_NAMES, key=len, reverse=True) if name in normalized), None)
    source_keyword = next((keyword for keyword in SOURCE_KEYWORDS if keyword in normalized), None)
    if person and source_keyword:
        if source_keyword in {"편지", "서찰"}:
            return f"{person} 어찰"
        return f"{person} {source_keyword}"
    if person:
        return person
    return None


def _build_rag_query(state: EditorAgentState) -> str:
    content_excerpt = _clean_markdown(state.get("content", ""))[:900]
    history_excerpt = _history_excerpt(state)
    return "\n".join(
        part
        for part in [
            f"사용자 질문: {state['message']}",
            f"최근 대화: {history_excerpt}" if history_excerpt else "",
            f"제목: {state['title']}" if state.get("title") else "",
            f"글 유형: {state.get('post_type', '')}",
            f"카테고리: {state.get('category', '')}" if state.get("category") else "",
            f"본문 발췌: {content_excerpt}" if content_excerpt else "",
        ]
        if part
    )


def _make_answer_plan(state: EditorAgentState, settings: Settings) -> dict[str, object]:
    fallback = _make_local_answer_plan(state)
    if not settings.openai_api_key:
        return fallback

    prompt = (
        "너는 역사 답변을 바로 쓰지 않고, 답변 전에 필요한 정보 구조를 계획하는 planner다. "
        "사용자 요청을 검증 가능한 하위 질문으로 쪼개고, 검색 후보를 만든다. "
        "특정 템플릿에 억지로 맞추지 말고 이번 질문에 실제로 필요한 질문만 고른다. "
        "검색 후보는 고유명사, 별칭, 한자명, 관련 사건/인물 단서를 포함하되 사실을 단정하지 않는다. "
        "JSON만 반환한다. 스키마: "
        '{"subject":"","required_questions":[""],"search_queries":[""],"answer_shape":""}\n'
        f"현재 제목: {state.get('title', '')}\n"
        f"현재 본문: {state.get('content', '')[:1200]}\n"
        f"글 유형: {state.get('post_type', '')}\n"
        f"카테고리: {state.get('category', '')}\n"
        f"사용자 메시지: {state.get('message', '')}\n"
    )
    try:
        payload = _extract_json(_generate_text(settings, prompt))
        return _normalize_answer_plan(payload, fallback)
    except Exception:
        return fallback


def _make_local_answer_plan(state: EditorAgentState) -> dict[str, object]:
    text = " ".join(
        part
        for part in [state.get("title", ""), state.get("content", "")[:500], state.get("message", "")]
        if part
    )
    terms = _extract_query_noun_terms(text)
    subject = _pick_plan_subject(terms, text)
    base = subject or (terms[0] if terms else state.get("message", "")[:30])
    required_questions = [
        f"{base}의 정체와 기본 배경은 무엇인가?",
        f"{base}에 대해 확인 가능한 핵심 사실은 무엇인가?",
        f"{base}와 직접 연결되는 주요 인물·사건·결과는 무엇인가?",
        "근거가 부족하거나 단정하면 안 되는 부분은 무엇인가?",
    ]
    search_queries = _dedupe_plan_items(
        [
            state.get("message", ""),
            base,
            *[f"{base} {term}" for term in terms[1:5] if term != base],
        ]
    )
    return {
        "subject": base,
        "required_questions": required_questions,
        "search_queries": search_queries,
        "answer_shape": "질문에 직접 답하고, 확인된 사실과 불확실한 부분을 분리한다.",
    }


def _normalize_answer_plan(payload: dict, fallback: dict[str, object]) -> dict[str, object]:
    subject = str(payload.get("subject") or fallback.get("subject") or "").strip()
    required_questions = _dedupe_plan_items(
        [str(item) for item in payload.get("required_questions", []) if str(item).strip()]
        + [str(item) for item in fallback.get("required_questions", []) if str(item).strip()]
    )[:8]
    fallback_queries = [str(item) for item in fallback.get("search_queries", []) if str(item).strip()]
    planner_queries = [str(item) for item in payload.get("search_queries", []) if str(item).strip()]
    search_queries = _dedupe_plan_items(
        fallback_queries[:2]
        + planner_queries
        + fallback_queries[2:]
    )[:10]
    answer_shape = str(payload.get("answer_shape") or fallback.get("answer_shape") or "").strip()
    return {
        "subject": subject,
        "required_questions": required_questions,
        "search_queries": search_queries,
        "answer_shape": answer_shape,
    }


def _pick_plan_subject(terms: list[str], text: str) -> str:
    if not terms:
        return ""
    for term in terms:
        if term in {"사용자", "질문", "본문", "게시글", "게시물", "포스트", "생애", "일생", "정리"}:
            continue
        if any(marker in term for marker in ["공주", "옹주", "대군", "군", "왕", "왕후", "부원군"]):
            return term
    return terms[0]


def _dedupe_plan_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = re.sub(r"\s+", " ", item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized[:100])
    return result


def _planned_external_keywords(state: EditorAgentState) -> list[str]:
    plan = state.get("answer_plan", {})
    queries = [str(item) for item in plan.get("search_queries", []) if str(item).strip()]
    queries.append(_external_keyword(state))
    return _select_external_keyword_budget(queries, str(plan.get("subject") or ""))


def _select_external_keyword_budget(queries: list[str], subject: str, limit: int = 5) -> list[str]:
    candidates = _dedupe_plan_items(queries)
    selected: list[str] = []
    subject = subject.strip()
    scored_candidates = [
        (query, _external_keyword_budget_score(query, subject))
        for query in candidates
    ]
    rich_query_count = sum(1 for query, score in scored_candidates if query != subject and score >= 4.0)
    if subject:
        exact_subject = next((query for query in candidates if query == subject), "")
        if exact_subject and rich_query_count < limit:
            selected.append(exact_subject)
    if not selected:
        short_anchor = next(
            (
                query
                for query in candidates
                if len(query) <= 20
                and len(_extract_query_noun_terms(query)) <= 2
                and _external_keyword_budget_score(query, subject) > 0
            ),
            "",
        )
        if short_anchor and rich_query_count < limit:
            selected.append(short_anchor)

    ranked = sorted(
        [query for query in candidates if query not in selected],
        key=lambda query: _external_keyword_budget_score(query, subject),
        reverse=True,
    )
    useful_ranked = [
        query
        for query in ranked
        if _external_keyword_budget_score(query, subject) > 0
    ]
    return _dedupe_plan_items([*selected, *useful_ranked])[:limit]


def _external_keyword_budget_score(query: str, subject: str) -> float:
    terms = _extract_query_noun_terms(query)
    compact_query = query.replace(" ", "")
    compact_subject = subject.replace(" ", "")
    score = 0.0
    if compact_subject and compact_subject in compact_query:
        score += 3.0
    if 2 <= len(terms) <= 5:
        score += 2.0
    elif len(terms) == 1:
        score += 0.5
    else:
        score -= min(len(terms), 12) * 0.12
    informative_terms = [term for term in terms if term not in _plan_query_stop_terms() and term != subject]
    score += min(len(informative_terms), 4) * 0.8
    if any(term in query for term in ["사료", "기록", "원문", "상소", "일화", "사건", "대표 인물"]):
        score += 0.7
    if any(re.search(r"(려던|됐는지|했는지|한다고|있다고|들었는데|해줘)$", term) for term in terms):
        score -= 1.6
    if re.search(r"[一-龥]", query):
        score += 1.0
    if len(query) > 60:
        score -= 1.5
    if any(term in compact_query for term in ["알려줘", "서술해줘", "설명해줘", "정리해줘", "있다고", "들었는데"]):
        score -= 5.0
    if any(term in compact_query for term in ["아닌", "아니라", "제외"]):
        score -= 3.0
    return score


def _plan_query_stop_terms() -> set[str]:
    return {
        "알려줘",
        "알려주세요",
        "서술해줘",
        "설명해줘",
        "정리해줘",
        "작성해줘",
        "있다고",
        "들었는데",
        "자세히",
        "인과관계",
        "무엇",
        "어떤",
        "부분",
        "관련",
    }


def _extract_evidence_claims(state: EditorAgentState, settings: Settings) -> list[dict[str, str]]:
    local_claims = _local_evidence_claims(state)
    if not settings.openai_api_key:
        return local_claims

    prompt = (
        "너는 역사 자료 검색 결과에서 최종 답변에 쓸 수 있는 claim만 추출한다. "
        "자료에 없는 사실은 만들지 말고, 각 claim은 한 문장으로 쓰며 source는 제목이나 URL로 표시한다. "
        "JSON만 반환한다. 스키마: {\"claims\":[{\"claim\":\"\",\"source\":\"\",\"status\":\"confirmed|uncertain\"}]}\n"
        f"답변 계획: {json.dumps(state.get('answer_plan', {}), ensure_ascii=False)}\n"
        f"RAG 근거: {json.dumps([item.model_dump() for item in state.get('citations', [])], ensure_ascii=False)[:5000]}\n"
        f"외부 자료: {json.dumps([item.model_dump() for item in state.get('external_resources', [])], ensure_ascii=False)[:7000]}"
    )
    try:
        payload = _extract_json(_generate_text(settings, prompt))
        claims = []
        for item in payload.get("claims", []):
            claim = str(item.get("claim") or "").strip()
            source = str(item.get("source") or "").strip()
            status = str(item.get("status") or "confirmed").strip()
            if claim:
                claims.append({"claim": claim[:500], "source": source[:300], "status": status[:30]})
        return claims[:12] or local_claims
    except Exception:
        return local_claims


def _local_evidence_claims(state: EditorAgentState) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    primary_resources = [
        resource
        for resource in state.get("external_resources", [])
        if resource.verification_status == "primary_verified"
    ]
    other_resources = [
        resource
        for resource in state.get("external_resources", [])
        if resource.verification_status != "primary_verified"
    ]
    for resource in [*primary_resources[:8], *other_resources[:4]]:
        excerpt = re.sub(r"\s+", " ", resource.content_excerpt or resource.description or "").strip()
        source = resource.url or resource.title
        if excerpt:
            status = "confirmed" if resource.verification_status == "primary_verified" else "uncertain"
            claims.append({"claim": excerpt[:280], "source": source, "status": status})
    for citation in state.get("citations", [])[:3]:
        summary = re.sub(r"\s+", " ", citation.summary).strip()
        if summary:
            claims.append({"claim": summary[:280], "source": citation.source_url or citation.title, "status": "confirmed"})
    return claims[:12]


def _check_plan_coverage(
    state: EditorAgentState,
    claims: list[dict[str, str]],
    settings: Settings,
) -> dict[str, object]:
    fallback = _local_coverage_check(state, claims)
    if not settings.openai_api_key:
        return fallback

    prompt = (
        "너는 답변 계획과 증거 claim의 coverage를 검사한다. "
        "답변을 쓰지 말고, 계획 질문 중 증거로 답할 수 있는 것과 부족한 것을 분류한다. "
        "JSON만 반환한다. 스키마: {\"covered\":[\"\"],\"missing\":[\"\"],\"revision_hints\":[\"\"]}\n"
        f"답변 계획: {json.dumps(state.get('answer_plan', {}), ensure_ascii=False)}\n"
        f"증거 claim: {json.dumps(claims, ensure_ascii=False)}"
    )
    try:
        payload = _extract_json(_generate_text(settings, prompt, model=settings.openai_judge_model))
        return {
            "covered": [str(item) for item in payload.get("covered", []) if str(item).strip()][:8],
            "missing": [str(item) for item in payload.get("missing", []) if str(item).strip()][:8],
            "revision_hints": [str(item) for item in payload.get("revision_hints", []) if str(item).strip()][:5],
        }
    except Exception:
        return fallback


def _local_coverage_check(state: EditorAgentState, claims: list[dict[str, str]]) -> dict[str, object]:
    questions = [str(item) for item in state.get("answer_plan", {}).get("required_questions", []) if str(item).strip()]
    haystack = " ".join(item.get("claim", "") for item in claims)
    covered: list[str] = []
    missing: list[str] = []
    for question in questions:
        terms = [term for term in _extract_query_noun_terms(question) if term not in {"무엇", "부분"}]
        if not terms or any(term in haystack for term in terms[:4]):
            covered.append(question)
        else:
            missing.append(question)
    return {
        "covered": covered[:8],
        "missing": missing[:8],
        "revision_hints": ["근거 claim에 있는 확인 사실은 최종 답변에서 누락하지 말 것."],
    }


def _make_llm_response(state: EditorAgentState, settings: Settings) -> EditorAgentResponse:
    action = state["action"]
    prompt = (
        "너는 역사 커뮤니티 에디터 안에서 동작하는 범용 Agent다. "
        "사용자가 역사 질문을 하면 답변하고, 본문 작성/수정 요청이면 게시글 본문을 작성한다. "
        "사실 기반으로 쓰되, 내부 RAG가 약하면 검증된 외부 검색 결과와 일반 역사 지식을 함께 활용하고 근거 한계를 밝혀라. "
        "external_resources에 primary_verified 원전 자료가 있으면, 질문과 직접 맞지 않는 내부 RAG보다 그 외부 원전 자료와 증거 claim을 우선하라. "
        "쉬운 인물 개괄 질문은 내부 RAG가 빗나갔다는 이유만으로 답변을 보류하지 말고, 확인 가능한 기본 사실을 먼저 설명하라. "
        "외부 자료의 verification_status가 secondary_only뿐이면 웹/백과/블로그 등 2차 자료에서 전하는 이야기로만 표시하고 사실로 단정하지 마라. "
        "이 경우 원하면 실록 등 원전 기준으로 더 찾아볼 수 있고 시간이 더 소요될 수 있다고 안내해라. "
        "외부 자료 배열이 비어 있으면 참고 링크, 외부 링크, 원문 링크를 만들거나 추측하지 마라. "
        "외부 자료 URL은 제공된 external_resources 안의 URL만 사용해라. "
        "널리 알려진 기본 사실은 설명해도 되지만, 구체적인 사료 인용처럼 보이게 꾸미지 마라. "
        "본문을 작성할 때는 suggested_content에 완성된 본문을 넣고, 태그는 tags 배열로만 제안하며 본문 끝에 해시태그를 붙이지 않는다. "
        "질문 답변일 때는 suggested_content를 null로 둔다. "
        "JSON만 반환한다. 스키마: "
        '{"action":"answer|fill_content|revise_content","agent_message":"","suggested_title":null,'
        '"suggested_content":null,"tags":[],"category":null,"questions":[]}\n'
        f"분류된 action: {action}\n"
        f"최근 대화: {json.dumps(_history_for_prompt(state), ensure_ascii=False)}\n"
        f"현재 제목: {state.get('title', '')}\n"
        f"글 유형: {state.get('post_type', '')}\n"
        f"카테고리: {state.get('category', '')}\n"
        f"현재 본문: {state.get('content', '')[:3000]}\n"
        f"사용자 메시지: {state['message']}\n"
        f"답변 계획: {json.dumps(state.get('answer_plan', {}), ensure_ascii=False)}\n"
        f"RAG 요약: {state.get('evidence_summary') or '없음'}\n"
        f"근거 제목: {[citation.title for citation in state.get('citations', [])]}\n"
        f"외부 자료: {json.dumps([resource.model_dump() for resource in state.get('external_resources', [])], ensure_ascii=False)}\n"
        f"증거 claim: {json.dumps(state.get('evidence_claims', []), ensure_ascii=False)}\n"
        f"coverage 검사: {json.dumps(state.get('coverage_report', {}), ensure_ascii=False)}"
    )
    try:
        payload = _extract_json(_generate_text(settings, prompt))
        return _normalize_response(payload, state)
    except Exception:
        return _make_local_response(state)


def _normalize_response(payload: dict, state: EditorAgentState) -> EditorAgentResponse:
    action = state["action"]
    agent_message = str(payload.get("agent_message") or _default_agent_message(state))
    agent_message = _append_verification_note(agent_message, state)
    suggested_content = _optional_text(payload.get("suggested_content"))
    if action == "answer":
        suggested_content = None
    if action in {"fill_content", "revise_content"} and _should_hold_content_for_primary_verification(state):
        suggested_content = None
        agent_message = _hold_for_primary_verification_message(state)
    return EditorAgentResponse(
        action=action,
        agent_message=agent_message,
        suggested_title=_optional_text(payload.get("suggested_title")),
        suggested_content=suggested_content,
        tags=[str(tag).lstrip("#") for tag in payload.get("tags", []) if str(tag).strip()],
        category=_optional_text(payload.get("category")) or state.get("category") or None,
        questions=[str(item) for item in payload.get("questions", []) if str(item).strip()],
        external_resources=state.get("external_resources", []),
        tool_logs=state.get("tool_logs", []),
    )


def _quality_gate_response(
    state: EditorAgentState,
    response: EditorAgentResponse,
    settings: Settings,
) -> tuple[EditorAgentResponse, list[AgentStep]]:
    if not settings.openai_api_key:
        return response, [AgentStep(name="quality.review", output="OpenAI API 키가 없어 품질 검토를 건너뛰었습니다.")]
    if not _needs_quality_review(state, response):
        return response, [AgentStep(name="quality.review", output="저위험 응답이라 추가 LLM 품질 검토를 건너뛰었습니다.")]

    try:
        review = _review_response_quality(state, response, settings)
    except Exception:
        return response, [AgentStep(name="quality.review", output="품질 검토 호출에 실패해 기존 응답을 유지했습니다.")]

    issue_text = "; ".join(review["issues"][:3]) or "주요 문제 없음"
    if review["passed"]:
        return response, [
            AgentStep(
                name="quality.review",
                output=f"LLM Judge 통과: score={review['score']:.2f}. {issue_text}",
            )
        ]

    revised_response = response
    revised = False
    try:
        revised_response = _revise_response_from_quality_review(state, response, review, settings)
        revised = True
    except Exception:
        revised_response = response

    status = "재작성 완료" if revised else "재작성 실패, 기존 응답 유지"
    return revised_response, [
        AgentStep(
            name="quality.review",
            output=f"LLM Judge 미통과: score={review['score']:.2f}. {issue_text}",
        ),
        AgentStep(name="quality.revise", output=status),
    ]


def _needs_quality_review(state: EditorAgentState, response: EditorAgentResponse) -> bool:
    resources = state.get("external_resources", [])
    answer_text = f"{response.agent_message}\n{response.suggested_content or ''}"
    if state.get("action") in {"fill_content", "revise_content"}:
        return True
    if state.get("weak_evidence"):
        return True
    if resources:
        return True
    if _asks_for_specific_factual_reconstruction(state):
        return True
    compact_message = state.get("message", "").replace(" ", "")
    if any(term in compact_message for term in ["원문", "인용", "실록", "사료", "편지", "어찰", "정확히", "사실관계"]):
        return True
    return len(answer_text) >= 700


def _review_response_quality(
    state: EditorAgentState,
    response: EditorAgentResponse,
    settings: Settings,
) -> QualityReview:
    prompt = (
        "너는 조선시대 역사 커뮤니티 AI 답변의 품질을 검사하는 LLM Judge다. "
        "답변을 새로 쓰지 말고 JSON만 반환한다. "
        "평가 기준: 사용자의 질문에 직접 답했는가, 쉬운 개괄 질문을 과도하게 회피하지 않았는가, "
        "답변 계획의 확인 질문 중 검색 claim으로 답할 수 있는 내용을 누락하지 않았는가, "
        "근거가 약한 세부 일화/원문 인용을 단정하지 않았는가, search_link를 citation처럼 쓰지 않았는가, "
        "외부 자료 URL을 꾸며내지 않았는가, 게시글 작성 요청이면 바로 쓸 수 있는 초안을 제공했는가. "
        "대표 인물/개괄 설명은 verified citation이 약해도 '대표적으로', '일반적으로' 같은 제한 표현을 쓰면 허용한다. "
        "특정 원문, 편지 일부, 누가 누구에게 무엇을 했는지 같은 세부 사실관계는 primary_verified 근거 없이는 보류해야 한다. "
        "단, 쉬운 인물 개괄 질문은 내부 RAG가 빗나갔더라도 external_resources나 증거 claim에 primary_verified 자료가 있으면 '근거 없음'으로 후퇴시키지 마라. "
        "JSON 스키마: {\"pass\":true,\"score\":0.0,\"issues\":[\"\"],\"revision_instruction\":\"\"}\n"
        f"사용자 메시지: {state.get('message', '')}\n"
        f"action: {state.get('action', '')}\n"
        f"weak_evidence: {state.get('weak_evidence', False)}\n"
        f"답변 계획: {json.dumps(state.get('answer_plan', {}), ensure_ascii=False)}\n"
        f"RAG 근거 제목: {[citation.title for citation in state.get('citations', [])]}\n"
        f"외부 자료: {json.dumps([resource.model_dump() for resource in state.get('external_resources', [])], ensure_ascii=False)}\n"
        f"증거 claim: {json.dumps(state.get('evidence_claims', []), ensure_ascii=False)}\n"
        f"coverage 검사: {json.dumps(state.get('coverage_report', {}), ensure_ascii=False)}\n"
        f"Agent 응답: {response.model_dump_json()[:5000]}"
    )
    payload = _extract_json(_generate_text(settings, prompt, model=settings.openai_judge_model))
    score = max(0.0, min(float(payload.get("score") or 0.0), 1.0))
    return {
        "passed": bool(payload.get("pass")) and score >= 0.72,
        "score": score,
        "issues": [str(item) for item in payload.get("issues", []) if str(item).strip()][:5],
        "revision_instruction": str(payload.get("revision_instruction") or "").strip(),
    }


def _revise_response_from_quality_review(
    state: EditorAgentState,
    response: EditorAgentResponse,
    review: QualityReview,
    settings: Settings,
) -> EditorAgentResponse:
    prompt = (
        "너는 역사 커뮤니티 에디터 Agent의 답변을 품질 검토 결과에 맞춰 한 번만 수정한다. "
        "제공된 RAG/외부 자료 범위를 넘는 URL이나 citation을 만들지 마라. "
        "증거 claim과 coverage 검사에 이미 확인된 사실이 있으면 최종 답변에서 누락하지 마라. "
        "external_resources에 primary_verified 원전 자료가 있으면, 질문과 직접 맞지 않는 내부 RAG보다 그 외부 원전 자료와 증거 claim을 우선하라. "
        "쉬운 인물 개괄 질문에서는 내부 RAG가 빗나갔다는 이유만으로 '자료가 없어 답할 수 없다'고 고치지 마라. "
        "대표 인물/개괄 설명은 제한 표현으로 답할 수 있지만, 원문 인용/세부 일화는 근거 없으면 보류하라. "
        "기존 응답의 JSON 스키마를 유지하고 JSON만 반환한다. "
        '{"action":"answer|fill_content|revise_content","agent_message":"","suggested_title":null,'
        '"suggested_content":null,"tags":[],"category":null,"questions":[]}\n'
        f"사용자 메시지: {state.get('message', '')}\n"
        f"현재 제목: {state.get('title', '')}\n"
        f"현재 본문: {state.get('content', '')[:2500]}\n"
        f"답변 계획: {json.dumps(state.get('answer_plan', {}), ensure_ascii=False)}\n"
        f"RAG 요약: {state.get('evidence_summary') or '없음'}\n"
        f"외부 자료: {json.dumps([resource.model_dump() for resource in state.get('external_resources', [])], ensure_ascii=False)}\n"
        f"증거 claim: {json.dumps(state.get('evidence_claims', []), ensure_ascii=False)}\n"
        f"coverage 검사: {json.dumps(state.get('coverage_report', {}), ensure_ascii=False)}\n"
        f"기존 응답: {response.model_dump_json()[:5000]}\n"
        f"품질 이슈: {review['issues']}\n"
        f"수정 지시: {review['revision_instruction']}"
    )
    payload = _extract_json(_generate_text(settings, prompt, model=settings.openai_judge_model))
    revised = _normalize_response(payload, state)
    if _revision_overcorrects_to_no_evidence(state, response, revised):
        revised = response
    return revised.model_copy(
        update={
            "external_resources": state.get("external_resources", []),
            "tool_logs": state.get("tool_logs", []),
            "evidence_summary": state.get("evidence_summary"),
            "weak_evidence": bool(state.get("weak_evidence", False)),
        }
    )


def _history_for_prompt(state: EditorAgentState) -> list[dict[str, str]]:
    return [
        {"role": item["role"], "content": item["content"][:1000]}
        for item in state.get("history", [])[-8:]
        if item.get("content")
    ]


def _history_excerpt(state: EditorAgentState) -> str:
    parts = []
    for item in state.get("history", [])[-4:]:
        content = _clean_markdown(item.get("content", ""))[:240]
        if content:
            parts.append(f"{item.get('role', 'user')}: {content}")
    return " / ".join(parts)


def _make_local_response(state: EditorAgentState) -> EditorAgentResponse:
    action = state["action"]
    tags = _extract_tags(state)
    if action in {"fill_content", "revise_content"}:
        if _should_hold_content_for_primary_verification(state):
            return EditorAgentResponse(
                action=action,
                agent_message=_hold_for_primary_verification_message(state),
                suggested_title=state.get("title") or _make_title_from_message(state["message"]),
                suggested_content=None,
                tags=tags,
                category=state.get("category") or _guess_category(tags),
                questions=[
                    "실록 기준으로 더 깊게 검증해볼까요? 시간이 더 소요될 수 있습니다.",
                    "원전 확인 전에는 전승 여부만 짧게 소개하는 방식으로 바꿀까요?",
                ],
                external_resources=state.get("external_resources", []),
                tool_logs=state.get("tool_logs", []),
            )
        content = _make_local_content(state, tags)
        return EditorAgentResponse(
            action=action,
            agent_message=_append_verification_note(
                "요청을 바탕으로 게시글 본문 초안을 만들었습니다. 사실과 해석이 섞일 수 있는 부분은 단정하지 않는 문장으로 처리했습니다.",
                state,
            ),
            suggested_title=state.get("title") or _make_title_from_message(state["message"]),
            suggested_content=content,
            tags=tags,
            category=state.get("category") or _guess_category(tags),
            questions=_default_questions(),
            external_resources=state.get("external_resources", []),
            tool_logs=state.get("tool_logs", []),
        )

    return EditorAgentResponse(
        action="answer",
        agent_message=_make_local_answer(state),
        suggested_title=None,
        suggested_content=None,
        tags=tags,
        category=state.get("category") or _guess_category(tags),
        questions=[],
        external_resources=state.get("external_resources", []),
        tool_logs=state.get("tool_logs", []),
    )


def _make_local_answer(state: EditorAgentState) -> str:
    evidence = state.get("evidence_summary")
    if evidence:
        suffix = _external_suffix(state)
        return _append_verification_note(
            f"질문에 대해 내부 RAG 근거를 먼저 확인했습니다. {evidence} "
            "다만 이 답변은 자료 범위 안에서의 해석이므로, 기록이 직접 말하지 않는 부분은 단정하지 않는 편이 좋습니다."
            f"{suffix}",
            state,
        )
    return _append_verification_note(
        "현재 질문과 직접 연결되는 내부 근거가 충분하지 않습니다. "
        "조선왕조실록 외부 검색에서도 표시할 수 있는 기사 링크를 확인하지 못했습니다. "
        "질문을 인물, 사건명, 시기 중심으로 좁히면 더 안정적인 근거를 찾기 좋습니다.",
        state,
    )


def _external_suffix(state: EditorAgentState) -> str:
    resources = state.get("external_resources", [])
    if not resources:
        return ""
    first = resources[0]
    return f" 외부 확인용으로는 {first.provider}의 `{first.title}` 자료를 함께 열어볼 수 있습니다."


def _append_verification_note(message: str, state: EditorAgentState) -> str:
    note = _verification_note(state)
    if not note or note in message:
        return message
    return f"{message}\n\n{note}"


def _verification_note(state: EditorAgentState) -> str:
    resources = state.get("external_resources", [])
    if not resources:
        return ""
    statuses = {getattr(resource, "verification_status", "") for resource in resources}
    has_primary = "primary_verified" in statuses
    has_secondary = "secondary_only" in statuses
    if has_secondary and not has_primary:
        return (
            "현재 확인된 내용은 원전으로 바로 검증된 사실이라기보다 2차 자료에서 전하는 이야기로 보아야 합니다. "
            "원하면 실록 등 원전 기준으로 해당 내용을 더 자세히 찾아볼 수 있습니다. 다만 시간이 더 소요될 수 있습니다."
        )
    return ""


def _should_hold_content_for_primary_verification(state: EditorAgentState) -> bool:
    if not _asks_for_specific_factual_reconstruction(state):
        return False
    return not _has_primary_verified_resource(state)


def _asks_for_specific_factual_reconstruction(state: EditorAgentState) -> bool:
    text = f"{state.get('title', '')} {state.get('content', '')[:500]} {state.get('message', '')}"
    compact = text.replace(" ", "")
    has_specific_event = any(term in compact for term in ["사건", "일화"])
    asks_detail = any(term in compact for term in ["사실관계", "인과관계", "자세히", "경위", "누구의", "재구성", "본문"])
    return has_specific_event and asks_detail


def _has_primary_verified_resource(state: EditorAgentState) -> bool:
    return any(
        getattr(resource, "verification_status", "") == "primary_verified"
        for resource in state.get("external_resources", [])
    )


def _revision_overcorrects_to_no_evidence(
    state: EditorAgentState,
    original: EditorAgentResponse,
    revised: EditorAgentResponse,
) -> bool:
    if not _has_primary_verified_resource(state):
        return False
    if not _is_easy_overview_question(state):
        return False
    revised_text = f"{revised.agent_message}\n{revised.suggested_content or ''}".replace(" ", "")
    original_text = f"{original.agent_message}\n{original.suggested_content or ''}".strip()
    if len(original_text) < 40:
        return False
    no_evidence_markers = [
        "직접정보가없",
        "직접연결되지않",
        "자료만으로는",
        "단정할수없",
        "답할수없",
        "근거자료에는",
        "근거가없",
        "확인할수없",
    ]
    return any(marker in revised_text for marker in no_evidence_markers)


def _is_easy_overview_question(state: EditorAgentState) -> bool:
    if state.get("action") != "answer":
        return False
    if _asks_for_specific_factual_reconstruction(state):
        return False
    compact = state.get("message", "").replace(" ", "")
    if any(term in compact for term in ["원문", "인용", "정확히", "사실관계", "인과관계", "자세히"]):
        return False
    return any(
        term in compact
        for term in ["어떤사람", "어떤인물", "누구", "무엇", "소개", "개괄", "알려줘", "정리해줘"]
    )


def _hold_for_primary_verification_message(state: EditorAgentState) -> str:
    return (
        "이 요청은 특정 일화의 사실관계와 인과관계를 자세히 재구성해야 하는데, 현재 확인된 외부 자료만으로는 원전 검증이 부족합니다. "
        "본문 초안을 길게 생성하면 확인되지 않은 전승을 사실처럼 보이게 만들 수 있어 생성하지 않았습니다. "
        "원하면 실록 등 원전 기준으로 더 깊게 찾아본 뒤, 확인된 범위 안에서 다시 본문을 구성할 수 있습니다. 시간이 더 소요될 수 있습니다."
    )


def _make_local_content(state: EditorAgentState, tags: list[str]) -> str:
    title = state.get("title") or _make_title_from_message(state["message"])
    content = _clean_markdown(state.get("content", ""))
    evidence = state.get("evidence_summary")
    base = content or state["message"]
    paragraphs = [
        f"{title}은 단순한 흥밋거리로만 보기보다, 기록에 남은 장면과 그 장면이 보여주는 시대 분위기를 함께 읽을 때 더 흥미롭습니다.",
        (
            f"현재 이야기의 핵심은 다음과 같습니다. {base[:320]} "
            "이 대목은 사건 자체의 재미뿐 아니라, 인물이 어떤 이미지로 기억되는지까지 생각하게 만듭니다."
        ),
        (
            f"내부 RAG에서 확인한 근거를 함께 보면, {evidence} "
            if evidence
            else "다만 내부 근거가 충분하지 않은 상태에서는, 장면을 꾸며내기보다 확인 가능한 사실과 해석을 분리해서 쓰는 편이 안전합니다. "
        )
        + "따라서 서술은 사실로 확인되는 부분을 먼저 놓고, 그 다음에 독자가 생각해볼 만한 해석을 덧붙이는 구조가 좋습니다.",
        "이 이야기가 흥미로운 이유는 사소한 일처럼 보이는 장면이 인물의 성격, 권력자의 체면, 당대 사회의 시선과 맞물리기 때문입니다. 독자는 웃고 넘길 수도 있지만, 동시에 왜 이런 기록이 남았고 왜 후대에 반복해서 소환되는지 묻게 됩니다.",
    ]
    return "\n\n".join(part for part in paragraphs if part)


def _default_agent_message(state: EditorAgentState) -> str:
    if state["action"] == "answer":
        return "질문에 답변했습니다."
    return "본문 초안을 생성했습니다."


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_tags(state: EditorAgentState) -> list[str]:
    source = f"{state.get('title', '')} {state.get('content', '')} {state['message']}"
    candidates = ["세조", "단종", "계유정난", "세종", "훈민정음", "문종", "붕당", "조선", "왕권", "사료"]
    tags = [tag for tag in candidates if tag in source]
    if not tags:
        tags = ["조선", "역사", state.get("post_type", "토론")]
    return list(dict.fromkeys(tags))[:5]


def _guess_category(tags: list[str]) -> str:
    if any(tag in tags for tag in ["세조", "단종", "문종", "왕권"]):
        return "왕과 권력"
    if any(tag in tags for tag in ["훈민정음", "세종"]):
        return "생활사와 문화"
    return "오늘의 떡밥"


def _make_title_from_message(message: str) -> str:
    cleaned = _clean_markdown(message)
    return (cleaned[:36] or "역사 이야기") + ("..." if len(cleaned) > 36 else "")


def _default_questions() -> list[str]:
    return [
        "이 사건을 당시 기준과 오늘날 기준으로 나누어 보면 평가가 달라질까요?",
        "기록이 직접 말하는 사실과 후대의 해석은 어디서 갈라질까요?",
    ]


def _clean_markdown(content: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", " ", content)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"[#>*_~|-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
