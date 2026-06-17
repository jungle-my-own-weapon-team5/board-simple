from __future__ import annotations

import re
from typing import TypedDict

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.ai import AgentStep, RagCitation, WritingAssistResponse
from app.services.ai_runtime import make_writing_assist, search_rag


class WritingAgentState(TypedDict, total=False):
    title: str
    content: str
    post_type: str
    instruction: str
    rag_query: str
    evidence_summary: str | None
    citations: list[RagCitation]
    weak_evidence: bool
    agent_steps: list[AgentStep]
    response: WritingAssistResponse
    graph_mode: str


def run_writing_assist_agent(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    post_type: str,
    instruction: str | None,
) -> WritingAssistResponse:
    initial_state: WritingAgentState = {
        "title": title.strip(),
        "content": content.strip(),
        "post_type": post_type,
        "instruction": (instruction or "").strip(),
        "agent_steps": [],
        "graph_mode": "langgraph",
    }

    try:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(WritingAgentState)
        graph.add_node("analyze_draft", _analyze_draft_node)
        graph.add_node("retrieve_evidence", lambda state: _retrieve_evidence_node(state, db, settings))
        graph.add_node("generate_recommendations", lambda state: _generate_recommendations_node(state, db, settings))
        graph.set_entry_point("analyze_draft")
        graph.add_edge("analyze_draft", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "generate_recommendations")
        graph.add_edge("generate_recommendations", END)
        result = graph.compile().invoke(initial_state)
    except ImportError:
        fallback_state: WritingAgentState = {**initial_state, "graph_mode": "local_fallback"}
        analyzed = {**fallback_state, **_analyze_draft_node(fallback_state)}
        retrieved = {**analyzed, **_retrieve_evidence_node(analyzed, db, settings)}
        result = {**retrieved, **_generate_recommendations_node(retrieved, db, settings)}

    return result["response"]


def _analyze_draft_node(state: WritingAgentState) -> WritingAgentState:
    query = _build_writing_rag_query(
        state["title"],
        state["content"],
        state["post_type"],
        state.get("instruction", ""),
    )
    keywords = _extract_keywords(query)
    steps = [
        *state.get("agent_steps", []),
        AgentStep(
            name="draft.analyze",
            output=(
                f"글 유형 `{state['post_type']}` 기준으로 제목, 본문, 작성 요청을 분석했습니다. "
                f"검색 키워드: {', '.join(keywords[:5]) if keywords else '없음'}"
            ),
        ),
    ]
    return {"rag_query": query, "agent_steps": steps}


def _retrieve_evidence_node(
    state: WritingAgentState,
    db: Session,
    settings: Settings,
) -> WritingAgentState:
    query = state["rag_query"]
    if not query.strip():
        return {
            "evidence_summary": None,
            "citations": [],
            "weak_evidence": True,
            "agent_steps": [
                *state.get("agent_steps", []),
                AgentStep(name="rag.search", output="검색할 초안 내용이 부족해 RAG 근거 조회를 건너뛰었습니다."),
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
                output=f"초안과 작성 요청으로 내부 RAG 근거 {len(result.citations)}건을 조회했습니다. 근거: {titles}",
            ),
        ],
    }


def _generate_recommendations_node(
    state: WritingAgentState,
    db: Session,
    settings: Settings,
) -> WritingAgentState:
    augmented_content = _build_augmented_content(state)
    response = make_writing_assist(
        db,
        settings,
        state["title"],
        augmented_content,
        state["post_type"],
    )
    graph_output = "초안과 근거를 바탕으로 추천을 생성했습니다."
    steps = [
        *state.get("agent_steps", []),
        AgentStep(name="draft.generate", output=graph_output),
    ]
    suggested_content = response.suggested_content or _make_local_suggested_content(
        state,
        response.tags,
    )
    return {
        "response": response.model_copy(
            update={
                "suggested_content": suggested_content,
                "agent_steps": steps,
                "evidence_summary": state.get("evidence_summary"),
                "weak_evidence": bool(state.get("weak_evidence", False)),
            }
        )
    }


def _build_writing_rag_query(
    title: str,
    content: str,
    post_type: str,
    instruction: str,
) -> str:
    cleaned_content = _clean_markdown(content)
    return "\n".join(
        part
        for part in [
            f"제목: {title}" if title else "",
            f"글 유형: {post_type}",
            f"작성 요청: {instruction}" if instruction else "",
            f"본문 발췌: {cleaned_content[:900]}" if cleaned_content else "",
        ]
        if part
    )


def _build_augmented_content(state: WritingAgentState) -> str:
    parts = [state["content"]]
    if state.get("instruction"):
        parts.append(f"작성 요청: {state['instruction']}")
    if state.get("evidence_summary"):
        parts.append(f"내부 RAG 근거 요약: {state['evidence_summary']}")
    citations = state.get("citations") or []
    if citations:
        parts.append("참고 근거 제목: " + ", ".join(citation.title for citation in citations[:2]))
    return "\n\n".join(part for part in parts if part)


def _make_local_suggested_content(state: WritingAgentState, tags: list[str]) -> str:
    title = state["title"] or "이 일화"
    cleaned_content = _clean_markdown(state["content"])
    instruction = state.get("instruction", "")
    evidence_summary = state.get("evidence_summary")
    citations = state.get("citations") or []
    citation_titles = ", ".join(citation.title for citation in citations[:2])
    tag_line = " ".join(f"#{tag.lstrip('#')}" for tag in tags[:5])

    opening = (
        f"{title}은 단순히 흥미로운 일화로만 넘기기보다, 기록에 남은 장면과 그 장면이 보여주는 시대적 맥락을 함께 살펴볼 때 더 선명해집니다."
    )
    if cleaned_content:
        source_part = (
            f"초안에서 제시된 핵심은 다음과 같습니다. {cleaned_content[:260]} "
            "이 대목은 사건 자체의 재미뿐 아니라, 인물의 이미지가 어떻게 만들어지고 후대에 어떻게 읽히는지를 생각하게 합니다."
        )
    else:
        source_part = (
            "현재 초안이 짧기 때문에, 먼저 확인 가능한 사실을 중심에 놓고 그 사실이 왜 흥미롭게 읽히는지부터 풀어가는 편이 좋습니다."
        )

    if evidence_summary:
        evidence_part = (
            f"내부 RAG에서 확인한 근거는 다음 방향을 보탭니다. {evidence_summary} "
            "따라서 서술은 확정되지 않은 심리나 장면을 꾸며내기보다, 기록이 말하는 사실과 해석 가능한 지점을 분리해서 전개하는 것이 안전합니다."
        )
    else:
        evidence_part = (
            "다만 현재 내부 근거가 충분하지 않다면, 표현은 단정형보다 가능성과 해석을 열어 두는 방식이 적절합니다."
        )

    citation_part = (
        f"특히 참고할 만한 근거 제목은 {citation_titles}입니다. "
        if citation_titles
        else ""
    )
    instruction_part = (
        f"사용자 요청은 `{instruction}`이므로, 문장은 더 길고 장면감 있게 이어가되 사실과 추정을 구분하는 방식으로 정리했습니다."
        if instruction
        else "댓글 토론으로 이어지도록 마지막에는 평가와 질문의 여지를 남기는 구성이 좋습니다."
    )
    closing = (
        "결국 이 일화의 재미는 사소함에만 있지 않습니다. 작은 행동 하나가 인물의 성격, 권력자의 체면, 당대 사회의 시선과 맞물리면서 오래 기억되는 이야기가 됩니다. "
        "읽는 사람은 이 사건을 웃고 넘길 수도 있지만, 동시에 왜 이런 장면이 기록되고 반복해서 소환되는지 질문하게 됩니다."
    )

    return "\n\n".join(
        part
        for part in [
            opening,
            source_part,
            evidence_part,
            citation_part + instruction_part,
            closing,
            tag_line,
        ]
        if part
    )


def _clean_markdown(content: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", " ", content)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"[#>*_~|-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_keywords(text: str) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for word in re.split(r"[\s,.:;!?()\[\]{}]+", text):
        normalized = word.strip()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(normalized)
    return keywords
