from __future__ import annotations

import json
import math
import time
from urllib.parse import quote_plus

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.ai import AiResponse, RagChunk, RagDocument, ToolLogRecord
from app.schemas.ai import (
    AgentRunResponse,
    AgentStep,
    DiscussionTopic,
    ExternalResource,
    ExternalSearchResponse,
    RagCitation,
    RagSearchResponse,
    ToolLog,
    WritingAssistResponse,
)
from app.services.ai_demo import (
    get_discussion_topics as get_demo_discussion_topics,
    make_writing_assist as make_demo_writing_assist,
    run_agent as run_demo_agent,
    search_external as search_demo_external,
    search_rag as search_demo_rag,
)

SEED_DOCUMENTS = [
    {
        "title": "계유정난과 왕권 재편",
        "period": "조선 전기",
        "source_url": "https://sillok.history.go.kr",
        "content": "계유정난은 세조와 단종을 둘러싼 권력 재편의 핵심 사건이다. 안정론과 찬탈론이 모두 존재하며, 명분과 결과를 나눠 토론하기 좋다.",
    },
    {
        "title": "훈민정음 창제와 정치적 맥락",
        "period": "세종",
        "source_url": "https://sillok.history.go.kr",
        "content": "훈민정음 창제는 애민정신과 함께 행정, 지식 보급, 통치 체계 변화라는 관점에서 해석할 수 있다.",
    },
    {
        "title": "붕당 정치의 논쟁 구조",
        "period": "조선 중기",
        "source_url": "https://sillok.history.go.kr",
        "content": "붕당 정치는 단순한 당파 싸움이 아니라 사림 정치, 공론, 권력 견제의 구조와 연결된다.",
    },
    {
        "title": "문종 평가와 짧은 재위",
        "period": "문종",
        "source_url": "https://sillok.history.go.kr",
        "content": "문종은 짧은 재위와 건강 문제 때문에 평가가 제한되지만, 세종 이후 제도 운영을 이어간 군주로 다시 볼 수 있다.",
    },
    {
        "title": "문종의 병환과 죽음",
        "period": "문종",
        "source_url": "https://sillok.history.go.kr",
        "content": "문종은 세종 말년부터 국정을 보좌했고 즉위 뒤에도 건강이 좋지 않았던 왕으로 알려져 있다. 문종의 죽음은 어린 단종의 즉위와 수양대군을 둘러싼 권력 구도 변화로 이어졌다.",
    },
    {
        "title": "단종 즉위와 권력 공백",
        "period": "단종",
        "source_url": "https://sillok.history.go.kr",
        "content": "문종 사후 단종이 어린 나이에 즉위하면서 조정의 권력 균형이 흔들렸다. 이 흐름은 훗날 계유정난과 세조 집권을 이해하는 배경이 된다.",
    },
]


def get_discussion_topics() -> list[DiscussionTopic]:
    return get_demo_discussion_topics()


def make_writing_assist(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    post_type: str,
) -> WritingAssistResponse:
    fallback = make_demo_writing_assist(title, content, post_type)
    if not settings.openai_api_key:
        return fallback

    prompt = (
        "너는 역사 커뮤니티 게시판의 글쓰기 보조자다. "
        "JSON만 반환한다. 스키마: "
        '{"improved_titles":[""],"tags":[""],"category":"","questions":[""],"keywords":[""]}\n'
        f"글 유형: {post_type}\n제목: {title}\n본문: {content[:3000]}"
    )
    try:
        output = _generate_text(settings, prompt)
        payload = _extract_json(output)
        result = WritingAssistResponse.model_validate(payload)
        _save_ai_response(db, "writing_assist", prompt, result.model_dump_json(), settings.openai_llm_model)
        return result
    except Exception:
        return fallback


def search_rag(db: Session, settings: Settings, query: str, top_k: int) -> RagSearchResponse:
    try:
        _ensure_seed_documents(db)
        if settings.openai_api_key:
            _ensure_chunk_embeddings(db, settings)
            query_embedding = _embed_text(settings, query)
            citations = _search_chunks_by_embedding(db, query_embedding, top_k)
        else:
            citations = _search_chunks_by_keyword(db, query, top_k)
        if not citations:
            return search_demo_rag(query, top_k)

        summary = _make_rag_summary(settings, query, citations)
        _save_ai_response(db, "rag_search", query, summary, settings.openai_llm_model if settings.openai_api_key else "local")
        return RagSearchResponse(
            answer_summary=summary,
            citations=citations,
            weak_evidence=len(citations) < 2,
        )
    except Exception:
        return search_demo_rag(query, top_k)


def search_external(db: Session, keyword: str) -> ExternalSearchResponse:
    started = time.perf_counter()
    search_url = f"https://sillok.history.go.kr/search/searchResultList.do?keyword={quote_plus(keyword)}"
    status = "link_ready"
    description = "조선왕조실록에서 직접 검색해볼 수 있는 외부 자료 링크입니다."

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    tool_log = ToolLog(
        tool="mcp.external_history_search",
        input=keyword,
        status=status,
        elapsed_ms=elapsed_ms,
    )
    _save_tool_log(db, tool_log, description)
    return ExternalSearchResponse(
        resources=[
            ExternalResource(
                title=f"{keyword} 조선왕조실록 검색",
                provider="국사편찬위원회 조선왕조실록",
                url=search_url,
                description=description,
            )
        ],
        tool_log=tool_log,
    )


def run_agent(db: Session, settings: Settings, goal: str, topic: str) -> AgentRunResponse:
    try:
        rag = search_rag(db, settings, topic, 3)
        external = search_external(db, topic)
        steps = [
            AgentStep(name="intent", output=f"목표 `{goal}`에 맞춰 필요한 도구를 선택했습니다."),
            AgentStep(name="rag.search", output=f"내부 근거 {len(rag.citations)}건을 조회했습니다."),
            AgentStep(name="mcp.external_search", output=f"외부 검색 상태: {external.tool_log.status}"),
        ]
        if settings.openai_api_key:
            prompt = (
                "아래 도구 실행 결과를 바탕으로 역사 게시판 사용자에게 줄 짧은 최종 답변을 작성해라. "
                "사실과 해석을 구분하고, 단정하지 말아라.\n"
                f"목표: {goal}\n주제: {topic}\nRAG 요약: {rag.answer_summary}\n"
                f"근거 제목: {[citation.title for citation in rag.citations]}"
            )
            final_answer = _generate_text(settings, prompt)
        else:
            final_answer = run_demo_agent(goal, topic).final_answer

        return AgentRunResponse(
            steps=steps,
            final_answer=final_answer,
            tool_logs=[
                ToolLog(tool="rag.search", input=topic, status="ok", elapsed_ms=0),
                external.tool_log,
            ],
        )
    except Exception:
        return run_demo_agent(goal, topic)


def _ensure_seed_documents(db: Session) -> None:
    for index, item in enumerate(SEED_DOCUMENTS):
        existing = db.scalar(select(RagDocument).where(RagDocument.title == item["title"]))
        if existing is not None:
            continue
        document = RagDocument(
            title=item["title"],
            period=item["period"],
            source_url=item["source_url"],
        )
        db.add(document)
        db.flush()
        db.add(
            RagChunk(
                document_id=document.id,
                chunk_index=index,
                content=item["content"],
            )
        )
    db.commit()


def _ensure_chunk_embeddings(db: Session, settings: Settings) -> None:
    chunks = db.scalars(select(RagChunk).where(RagChunk.embedding_json.is_(None))).all()
    for chunk in chunks:
        embedding = _embed_text(settings, chunk.content)
        chunk.embedding_json = json.dumps(embedding)
    if chunks:
        db.commit()


def _search_chunks_by_keyword(db: Session, query: str, top_k: int) -> list[RagCitation]:
    keywords = _query_keywords(query)
    documents = {document.id: document for document in db.scalars(select(RagDocument)).all()}
    chunks = db.scalars(select(RagChunk)).all()

    scored = []
    for chunk in chunks:
        haystack = chunk.content + " " + documents[chunk.document_id].title
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    return _dedupe_citations(
        [
            _citation_from_chunk(documents[chunk.document_id], chunk, 0.5 + min(score, 5) * 0.1)
            for score, chunk in scored
        ],
        top_k,
    )


def _search_chunks_by_embedding(
    db: Session,
    query_embedding: list[float],
    top_k: int,
) -> list[RagCitation]:
    documents = {document.id: document for document in db.scalars(select(RagDocument)).all()}
    chunks = db.scalars(select(RagChunk).where(RagChunk.embedding_json.is_not(None))).all()
    scored = []
    for chunk in chunks:
        embedding = json.loads(chunk.embedding_json or "[]")
        scored.append((_cosine_similarity(query_embedding, embedding), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return _dedupe_citations(
        [
            _citation_from_chunk(documents[chunk.document_id], chunk, max(0.0, min(score, 1.0)))
            for score, chunk in scored
        ],
        top_k,
    )


def _citation_from_chunk(document: RagDocument, chunk: RagChunk, relevance: float) -> RagCitation:
    return RagCitation(
        id=f"rag-{chunk.id}",
        title=document.title,
        period=document.period,
        summary=chunk.content,
        relevance=round(relevance, 3),
        source_url=document.source_url,
    )


def _dedupe_citations(citations: list[RagCitation], top_k: int) -> list[RagCitation]:
    seen: set[str] = set()
    unique: list[RagCitation] = []
    for citation in citations:
        key = f"{citation.title}:{citation.summary}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(citation)
        if len(unique) >= top_k:
            break
    return unique


def _make_rag_summary(settings: Settings, query: str, citations: list[RagCitation]) -> str:
    if not settings.openai_api_key:
        if citations:
            titles = ", ".join(citation.title for citation in citations[:2])
            return f"`{query}` 주제와 관련된 내부 RAG seed 자료를 찾았습니다: {titles}. 자료 범위 안에서만 근거와 해석 지점을 나눠 보세요."
        return "내부 RAG seed 자료에서 직접 관련 근거를 찾지 못했습니다. seed 데이터를 추가하거나 외부 자료를 확인해야 합니다."
    prompt = (
        "역사 게시판의 RAG 근거 요약을 3문장 이내로 작성해라. "
        "자료에 없는 내용은 단정하지 말아라.\n"
        f"질문: {query}\n근거: {json.dumps([item.model_dump() for item in citations], ensure_ascii=False)}"
    )
    return _generate_text(settings, prompt)


def _generate_text(settings: Settings, prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_llm_model,
        input=prompt,
    )
    return response.output_text


def _embed_text(settings: Settings, text: str) -> list[float]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return response.data[0].embedding


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _query_keywords(query: str) -> list[str]:
    normalized = query.replace("#", " ").replace("의", " ").replace(",", " ")
    seen: set[str] = set()
    keywords: list[str] = []
    for word in normalized.split():
        word = word.strip()
        if len(word) >= 2 and word not in seen:
            seen.add(word)
            keywords.append(word)
    return keywords


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found")
    return json.loads(text[start : end + 1])


def _save_ai_response(
    db: Session,
    feature: str,
    input_text: str,
    output_text: str,
    model: str,
) -> None:
    try:
        db.add(
            AiResponse(
                feature=feature,
                input_text=input_text,
                output_text=output_text,
                model=model,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _save_tool_log(db: Session, tool_log: ToolLog, result_summary: str) -> None:
    try:
        db.add(
            ToolLogRecord(
                tool=tool_log.tool,
                input_text=tool_log.input,
                status=tool_log.status,
                elapsed_ms=tool_log.elapsed_ms,
                result_summary=result_summary,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
