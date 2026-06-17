from __future__ import annotations

import json
import re
from typing import Literal, TypedDict

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.ai import AgentStep, EditorAgentHistoryMessage, EditorAgentResponse, ExternalResource, RagCitation, ToolLog
from app.services.ai_runtime import _extract_json, _generate_text, search_external, search_rag
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
]
SOURCE_KEYWORDS = ["어찰", "편지", "서찰", "문서", "일기", "실록", "사료", "원문", "국역"]


class EditorAgentState(TypedDict, total=False):
    title: str
    content: str
    post_type: str
    category: str
    message: str
    history: list[dict[str, str]]
    action: EditorAction
    rag_query: str
    evidence_summary: str | None
    citations: list[RagCitation]
    external_resources: list[ExternalResource]
    tool_logs: list[ToolLog]
    weak_evidence: bool
    agent_steps: list[AgentStep]
    response: EditorAgentResponse
    graph_mode: str


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
        graph.add_node("retrieve", lambda state: _retrieve_node(state, db, settings))
        graph.add_node("external_search", lambda state: _external_search_node(state, db, settings))
        graph.add_node("respond", lambda state: _respond_node(state, settings))
        graph.set_entry_point("intent")
        graph.add_edge("intent", "retrieve")
        graph.add_edge("retrieve", "external_search")
        graph.add_edge("external_search", "respond")
        graph.add_edge("respond", END)
        result = graph.compile().invoke(initial_state)
    except ImportError:
        fallback_state: EditorAgentState = {**initial_state, "graph_mode": "local_fallback"}
        intended = {**fallback_state, **_intent_node(fallback_state)}
        retrieved = {**intended, **_retrieve_node(intended, db, settings)}
        external = {**retrieved, **_external_search_node(retrieved, db, settings)}
        result = {**external, **_respond_node(external, settings)}

    return result["response"]


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

    result = search_rag(db, settings, query, 3)
    usable_citations = _usable_citations(result.citations)
    weak_evidence = result.weak_evidence or not usable_citations
    titles = ", ".join(citation.title for citation in usable_citations[:2]) or "없음"
    return {
        "evidence_summary": result.answer_summary if not weak_evidence else None,
        "citations": usable_citations,
        "weak_evidence": weak_evidence,
        "agent_steps": [
            *state.get("agent_steps", []),
            AgentStep(
                name="rag.search",
                output=(
                    f"관련 내부 RAG 근거 {len(usable_citations)}건을 조회했습니다. 근거: {titles}"
                    if not weak_evidence
                    else f"내부 RAG에서 직접 근거로 쓰기 어려운 결과만 확인했습니다. 후보: {titles}"
                ),
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

    keyword = _external_keyword(state)
    result = search_external(db, settings, keyword)
    return {
        "external_resources": result.resources,
        "tool_logs": [result.tool_log],
        "agent_steps": [
            *state.get("agent_steps", []),
            AgentStep(
                name="external.search",
                output=f"`{keyword}` 외부 자료 검색을 실행했습니다. 상태: {result.tool_log.status}",
            ),
        ],
    }


def _respond_node(state: EditorAgentState, settings: Settings) -> EditorAgentState:
    if settings.openai_api_key:
        response = _make_llm_response(state, settings)
    else:
        response = _make_local_response(state)

    graph_output = (
        "LangGraph 노드 흐름으로 응답을 생성했습니다."
        if state.get("graph_mode") == "langgraph"
        else "LangGraph 패키지가 없는 환경이라 같은 순서를 로컬 fallback으로 처리했습니다."
    )
    return {
        "response": response.model_copy(
            update={
                "agent_steps": [
                    *state.get("agent_steps", []),
                    AgentStep(name="respond", output=graph_output),
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

    for term in ["알려줘", "설명해줘", "어떤", "사람이야", "사람인가", "누구야", "뭐야", "인가요"]:
        text = text.replace(term, " ")
    text = re.sub(r"[?!.~,;:()\[\]{}]", " ", text)
    text = re.sub(r"\b(은|는|이|가|을|를|의|에|와|과)\b", " ", text)
    candidates = [_strip_korean_particle(word.strip()) for word in text.split()]
    candidates = [word for word in candidates if len(word) >= 2]
    if candidates:
        return candidates[0][:40]
    return (state.get("title") or state["message"])[:40]


def _focused_external_keyword(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip()
    person = next((name for name in KING_NAMES if name in normalized), None)
    source_keyword = next((keyword for keyword in SOURCE_KEYWORDS if keyword in normalized), None)
    if person and source_keyword:
        if source_keyword in {"편지", "서찰"}:
            return f"{person} 어찰"
        return f"{person} {source_keyword}"
    if person:
        return person
    return None


def _strip_korean_particle(word: str) -> str:
    return re.sub(r"(은|는|이|가|을|를|의|에|와|과)$", "", word)


def _build_rag_query(state: EditorAgentState) -> str:
    content_excerpt = _clean_markdown(state.get("content", ""))[:900]
    return "\n".join(
        part
        for part in [
            f"사용자 질문: {state['message']}",
            f"제목: {state['title']}" if state.get("title") else "",
            f"글 유형: {state.get('post_type', '')}",
            f"카테고리: {state.get('category', '')}" if state.get("category") else "",
            f"본문 발췌: {content_excerpt}" if content_excerpt else "",
        ]
        if part
    )


def _make_llm_response(state: EditorAgentState, settings: Settings) -> EditorAgentResponse:
    action = state["action"]
    evidence_summary = state.get("evidence_summary") if not state.get("weak_evidence") else None
    citations = state.get("citations", []) if not state.get("weak_evidence") else []
    prompt = (
        "너는 역사 커뮤니티 에디터 안에서 동작하는 범용 Agent다. "
        "사용자가 역사 질문을 하면 답변하고, 본문 작성/수정 요청이면 게시글 본문을 작성한다. "
        "사실 기반으로 쓰되, 내부 RAG가 약하면 검증된 외부 검색 결과와 일반 역사 지식을 함께 활용하고 근거 한계를 밝혀라. "
        "weak_evidence가 true이면 RAG 요약이나 근거 제목을 사실 근거처럼 사용하지 말고, 내부 근거가 부족하다고 말해라. "
        "사용자의 현재 질문에 직접 답하고, 최근 대화의 이전 인물이나 이전 오류 문구를 현재 인물의 근거로 섞지 마라. "
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
        f"weak_evidence: {bool(state.get('weak_evidence', False))}\n"
        f"RAG 요약: {evidence_summary or '없음'}\n"
        f"근거 제목: {[citation.title for citation in citations]}\n"
        f"외부 자료: {json.dumps([resource.model_dump() for resource in state.get('external_resources', [])], ensure_ascii=False)}"
    )
    try:
        payload = _extract_json(_generate_text(settings, prompt))
        return _normalize_response(payload, state)
    except Exception:
        return _make_local_response(state)


def _normalize_response(payload: dict, state: EditorAgentState) -> EditorAgentResponse:
    action = str(payload.get("action") or state["action"])
    if action not in {"answer", "fill_content", "revise_content"}:
        action = state["action"]
    return EditorAgentResponse(
        action=action,
        agent_message=str(payload.get("agent_message") or _default_agent_message(state)),
        suggested_title=_optional_text(payload.get("suggested_title")),
        suggested_content=_optional_text(payload.get("suggested_content")),
        tags=[str(tag).lstrip("#") for tag in payload.get("tags", []) if str(tag).strip()],
        category=_optional_text(payload.get("category")) or state.get("category") or None,
        questions=[str(item) for item in payload.get("questions", []) if str(item).strip()],
        external_resources=state.get("external_resources", []),
        tool_logs=state.get("tool_logs", []),
    )


def _history_for_prompt(state: EditorAgentState) -> list[dict[str, str]]:
    return [
        {"role": item["role"], "content": _clean_history_for_prompt(item["content"])[:500]}
        for item in state.get("history", [])[-4:]
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
        content = _make_local_content(state, tags)
        return EditorAgentResponse(
            action=action,
            agent_message="요청을 바탕으로 게시글 본문 초안을 만들었습니다. 사실과 해석이 섞일 수 있는 부분은 단정하지 않는 문장으로 처리했습니다.",
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
    known_answer = _known_person_answer(state["message"])
    if known_answer:
        suffix = _external_suffix(state)
        return f"{known_answer}{suffix}"

    if state.get("weak_evidence"):
        suffix = _external_suffix(state)
        return (
            "현재 질문과 직접 연결되는 내부 RAG 근거가 충분하지 않습니다. "
            "확인되지 않은 근거를 억지로 연결하지 않겠습니다. "
            "인물의 한자명, 활동 시기, 관련 왕대나 사건을 함께 주면 더 안정적으로 찾을 수 있습니다."
            f"{suffix}"
        )

    evidence = state.get("evidence_summary")
    if evidence:
        suffix = _external_suffix(state)
        return (
            f"질문에 대해 내부 RAG 근거를 먼저 확인했습니다. {evidence} "
            "다만 이 답변은 자료 범위 안에서의 해석이므로, 기록이 직접 말하지 않는 부분은 단정하지 않는 편이 좋습니다."
            f"{suffix}"
        )
    return (
        "현재 질문과 직접 연결되는 내부 근거가 충분하지 않습니다. "
        "조선왕조실록 외부 검색에서도 표시할 수 있는 기사 링크를 확인하지 못했습니다. "
        "질문을 인물, 사건명, 시기 중심으로 좁히면 더 안정적인 근거를 찾기 좋습니다."
    )


def _known_person_answer(message: str) -> str | None:
    if "양녕대군" not in message:
        return None
    return (
        "양녕대군은 조선 태종의 맏아들이자 세종의 형입니다. 본래 왕세자로 책봉되었지만, 여러 문제와 정치적 판단 속에서 폐세자가 되었고, "
        "결국 왕위는 충녕대군, 곧 세종에게 이어졌습니다. 후대에는 자유분방하고 예법에 얽매이지 않는 인물로 자주 기억되지만, "
        "그 이미지는 일화와 후대 해석이 섞여 있으므로 조심해서 볼 필요가 있습니다. 핵심은 그를 단순한 방탕한 왕자나 실패한 세자로만 보기보다, "
        "태종 말기 왕위 계승과 조선 왕실의 정치 질서 속에서 이해하는 것입니다."
    )


def _external_suffix(state: EditorAgentState) -> str:
    resources = state.get("external_resources", [])
    if not resources:
        return ""
    first = resources[0]
    return f" 외부 확인용으로는 {first.provider}의 `{first.title}` 자료를 함께 열어볼 수 있습니다."


def _usable_citations(citations: list[RagCitation]) -> list[RagCitation]:
    return [citation for citation in citations if citation.relevance >= 0.55]


def _clean_history_for_prompt(content: str) -> str:
    cleaned = _clean_markdown(content)
    cleaned = re.sub(r"이 서비스는 역사.*?다시 작성해 주세요\.?", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


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
