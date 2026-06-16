from __future__ import annotations

import json
import math
import re
import time
from html import unescape
from pathlib import Path
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
    RagQualityAgentResponse,
    RagQualityAttempt,
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

RAG_SEED_DIR = Path(__file__).resolve().parents[2] / "rag_seed"
_SYNCED_SEED_BINDS: set[int] = set()
EMBEDDING_MIN_RELEVANCE = 0.45

KNOWN_RAG_TERMS = [
    "계유정난",
    "훈민정음",
    "세종",
    "문종",
    "단종",
    "세조",
    "붕당",
    "식성",
    "식생활",
    "음식",
    "건강",
    "죽음",
    "병환",
    "재위",
    "왕권",
]

RAG_HANJA_ALIASES = [
    ("訓民正音", "훈민정음"),
    ("癸酉靖難", "계유정난"),
    ("丁未約條", "정미약조"),
    ("壬辰倭亂", "임진왜란"),
    ("丙子胡亂", "병자호란"),
    ("科田法", "과전법"),
    ("經國大典", "경국대전"),
    ("集賢殿", "집현전"),
    ("對馬島", "대마도"),
    ("大內", "대내씨"),
    ("小貳殿", "소이전/소이씨"),
    ("事大交隣", "사대교린"),
    ("斥佛崇儒", "척불숭유"),
    ("崇儒抑佛", "숭유억불"),
    ("弘文館", "홍문관"),
    ("奎章閣", "규장각"),
    ("蕩平策", "탕평책"),
    ("大同法", "대동법"),
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


def make_post_search_summary(
    db: Session,
    settings: Settings,
    title: str,
    content: str,
    post_type: str,
    category: str,
    tags: list[str],
) -> str:
    fallback = _make_local_post_search_summary(title, content, post_type, category, tags)
    if not settings.openai_api_key:
        return fallback

    prompt = (
        "역사 커뮤니티 게시글을 RAG 검색에 잘 걸리도록 검색용 요약을 작성해라. "
        "사용자의 주장/질문, 핵심 인물, 사건, 시대, 태그를 보존하고 자료에 없는 사실을 추가하지 마라. "
        "한국어 600자 이내의 평문만 반환해라.\n"
        f"제목: {title}\n"
        f"글 유형: {post_type}\n"
        f"카테고리: {category}\n"
        f"태그: {', '.join(tags) if tags else '없음'}\n"
        f"본문: {content[:3000]}"
    )
    try:
        summary = _generate_text(settings, prompt).strip()
        if not summary:
            return fallback
        summary = summary[:1000]
        _save_ai_response(db, "post_search_summary", prompt, summary, settings.openai_llm_model)
        return summary
    except Exception:
        return fallback


def search_rag(db: Session, settings: Settings, query: str, top_k: int) -> RagSearchResponse:
    try:
        _ensure_seed_documents(db)
        if settings.openai_api_key:
            query_embedding = _embed_text(settings, query)
            citations = _search_chunks_by_embedding(db, query_embedding, top_k)
            if not citations:
                citations = _search_chunks_by_keyword(db, query, top_k)
        else:
            citations = _search_chunks_by_keyword(db, query, top_k)
        if not citations:
            return RagSearchResponse(
                answer_summary=(
                    f"`{query}` 주제와 직접 연결되는 내부 RAG seed 근거를 찾지 못했습니다. "
                    "외부 자료 링크를 확인하거나 seed 문서를 추가해야 합니다."
                ),
                citations=[],
                weak_evidence=True,
            )

        summary = _make_rag_summary(settings, query, citations)
        _save_ai_response(db, "rag_search", query, summary, settings.openai_llm_model if settings.openai_api_key else "local")
        return RagSearchResponse(
            answer_summary=summary,
            citations=citations,
            weak_evidence=len(citations) < 2,
        )
    except Exception:
        return search_demo_rag(query, top_k)


def run_rag_quality_agent(
    db: Session,
    settings: Settings,
    query: str,
    top_k: int,
) -> RagQualityAgentResponse:
    agent_steps = [
        AgentStep(name="intent", output="RAG 결과 품질을 높이기 위해 원 질의 검색과 재작성 검색을 계획했습니다."),
    ]
    candidate_queries = _build_rag_agent_queries(settings, query)
    attempts: list[RagQualityAttempt] = []
    collected_citations: list[RagCitation] = []
    best_query = candidate_queries[0]
    best_result: RagSearchResponse | None = None
    best_score = -1.0

    for index, candidate_query in enumerate(candidate_queries, start=1):
        result = search_rag(db, settings, candidate_query, top_k)
        collected_citations.extend(result.citations)
        score = _score_rag_result(result)
        decision = _judge_rag_result(result)
        attempts.append(
            RagQualityAttempt(
                query=candidate_query,
                citation_count=len(result.citations),
                max_relevance=max((citation.relevance for citation in result.citations), default=0.0),
                weak_evidence=result.weak_evidence,
                decision=decision,
            )
        )
        agent_steps.append(
            AgentStep(
                name=f"rag.search.{index}",
                output=f"`{candidate_query}` 검색: citation {len(result.citations)}건, 판단 `{decision}`",
            )
        )
        if score > best_score:
            best_score = score
            best_query = candidate_query
            best_result = result
        if _is_strong_rag_result(result):
            agent_steps.append(
                AgentStep(name="quality.stop", output="충분한 관련도와 citation 수를 확보해 추가 검색을 중단했습니다.")
            )
            break
        if index < len(candidate_queries):
            agent_steps.append(
                AgentStep(name="query.rewrite", output="근거가 약해 고유명사와 사건명 중심으로 질의를 재작성했습니다.")
            )

    if best_result is None:
        best_result = search_rag(db, settings, query, top_k)

    merged_citations = _merge_agent_citations(collected_citations or best_result.citations, top_k)
    weak_evidence = len(merged_citations) < 2 or max((item.relevance for item in merged_citations), default=0.0) < 0.55
    summary = _make_rag_agent_summary(settings, query, best_query, merged_citations, weak_evidence)
    suggested_external_keywords = _suggest_external_keywords(query, best_query, merged_citations)
    needs_external_search = weak_evidence
    agent_steps.append(
        AgentStep(
            name="quality.final",
            output=(
                "내부 RAG 근거가 부족해 외부 검색 보강을 권장합니다."
                if needs_external_search
                else "내부 RAG 근거만으로 우선 답변 가능한 수준입니다."
            ),
        )
    )

    _save_ai_response(
        db,
        "rag_quality_agent",
        query,
        summary,
        settings.openai_llm_model if settings.openai_api_key else "local",
    )
    return RagQualityAgentResponse(
        final_query=best_query,
        answer_summary=summary,
        citations=merged_citations,
        weak_evidence=weak_evidence,
        attempts=attempts,
        agent_steps=agent_steps,
        needs_external_search=needs_external_search,
        suggested_external_keywords=suggested_external_keywords,
    )


def _build_rag_agent_queries(settings: Settings, query: str) -> list[str]:
    local_queries = _local_rag_query_variants(query)
    if not settings.openai_api_key:
        return local_queries

    prompt = (
        "역사 RAG 검색 품질을 높이기 위한 한국어 검색 질의 후보를 만들어라. "
        "JSON만 반환한다. 스키마: {\"queries\":[\"\"]}. "
        "첫 번째 query는 원문 질의를 유지하고, 이후 query는 인물/사건/시대/핵심 명사 중심으로 재작성한다. "
        "너무 긴 문장이나 추측성 표현은 피하고 최대 3개만 반환한다.\n"
        f"원 질의: {query}"
    )
    try:
        payload = _extract_json(_generate_text(settings, prompt))
        llm_queries = [str(item).strip() for item in payload.get("queries", []) if str(item).strip()]
        return _dedupe_query_candidates([query, *llm_queries, *local_queries])[:3]
    except Exception:
        return local_queries


def _local_rag_query_variants(query: str) -> list[str]:
    keywords = _query_keywords(query)
    candidates = [query.strip()]
    if keywords:
        candidates.append(" ".join(keywords[:5]))
    if len(keywords) >= 2:
        candidates.append(f"{keywords[0]} {keywords[1]} 실록 기록")
    return _dedupe_query_candidates(candidates)[:3]


def _dedupe_query_candidates(candidates: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _score_rag_result(result: RagSearchResponse) -> float:
    if not result.citations:
        return 0.0
    max_relevance = max(citation.relevance for citation in result.citations)
    avg_relevance = sum(citation.relevance for citation in result.citations) / len(result.citations)
    count_bonus = min(len(result.citations), 3) * 0.08
    weak_penalty = 0.2 if result.weak_evidence else 0.0
    return max_relevance * 0.6 + avg_relevance * 0.4 + count_bonus - weak_penalty


def _judge_rag_result(result: RagSearchResponse) -> str:
    if not result.citations:
        return "no_citation"
    max_relevance = max(citation.relevance for citation in result.citations)
    if _is_strong_rag_result(result):
        return "strong"
    if len(result.citations) >= 2 and max_relevance >= 0.5:
        return "usable_but_needs_review"
    return "weak_retry_needed"


def _is_strong_rag_result(result: RagSearchResponse) -> bool:
    if len(result.citations) < 2 or result.weak_evidence:
        return False
    return max((citation.relevance for citation in result.citations), default=0.0) >= 0.62


def _merge_agent_citations(citations: list[RagCitation], top_k: int) -> list[RagCitation]:
    sorted_citations = sorted(citations, key=lambda item: item.relevance, reverse=True)
    return _dedupe_citations(sorted_citations, top_k)


def _make_rag_agent_summary(
    settings: Settings,
    original_query: str,
    final_query: str,
    citations: list[RagCitation],
    weak_evidence: bool,
) -> str:
    if not citations:
        return (
            f"`{original_query}`에 대해 여러 질의를 시도했지만 내부 RAG에서 기준치 이상의 근거를 찾지 못했습니다. "
            "외부 실록 검색이나 seed 문서 추가가 필요합니다."
        )
    if not settings.openai_api_key:
        status = "근거가 약합니다" if weak_evidence else "우선 활용 가능한 근거를 찾았습니다"
        titles = ", ".join(citation.title for citation in citations[:2])
        return f"{status}. 최종 질의 `{final_query}` 기준으로 {titles} 자료를 우선 확인하세요."

    prompt = (
        "역사 게시판의 RAG 품질 개선 Agent 결과를 3문장 이내로 요약해라. "
        "근거가 약하면 약하다고 말하고 외부 검색 필요성을 분명히 표시해라. "
        "자료에 없는 사실은 단정하지 마라.\n"
        f"원 질의: {original_query}\n최종 질의: {final_query}\n"
        f"weak_evidence: {weak_evidence}\n"
        f"citations: {json.dumps([citation.model_dump() for citation in citations], ensure_ascii=False)}"
    )
    try:
        return _generate_text(settings, prompt)
    except Exception:
        titles = ", ".join(citation.title for citation in citations[:2])
        return f"`{final_query}` 기준으로 {titles} 자료를 찾았습니다. 관련도와 근거 강도를 함께 확인해야 합니다."


def _suggest_external_keywords(
    original_query: str,
    final_query: str,
    citations: list[RagCitation],
) -> list[str]:
    keywords = [final_query, original_query]
    for citation in citations[:2]:
        if citation.title:
            keywords.append(citation.title)
    return _dedupe_query_candidates(keywords)[:3]


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
    bind_id = id(db.get_bind())
    document_count = db.scalar(select(func.count()).select_from(RagDocument)) or 0
    if bind_id in _SYNCED_SEED_BINDS and document_count > 0:
        return

    for item in _load_seed_documents():
        existing = _find_existing_seed_document(db, item)
        if existing is None:
            document = RagDocument(
                title=item["title"],
                period=item["period"],
                source_url=item["source_url"],
            )
            db.add(document)
            db.flush()
        else:
            document = existing
            document.period = item["period"]
            document.source_url = item["source_url"]

        current_chunks = db.scalars(
            select(RagChunk)
            .where(RagChunk.document_id == document.id)
            .order_by(RagChunk.chunk_index)
        ).all()
        next_chunks = _chunk_seed_content(item["content"])
        if [chunk.content for chunk in current_chunks] == next_chunks:
            continue

        for chunk in current_chunks:
            db.delete(chunk)
        db.flush()
        for index, content in enumerate(next_chunks):
            db.add(RagChunk(document_id=document.id, chunk_index=index, content=content))
    db.commit()
    _SYNCED_SEED_BINDS.add(bind_id)


def _find_existing_seed_document(db: Session, item: dict[str, str]) -> RagDocument | None:
    source_url = item["source_url"]
    if _is_unique_seed_source_url(source_url):
        return db.scalar(select(RagDocument).where(RagDocument.source_url == source_url))
    return db.scalar(select(RagDocument).where(RagDocument.title == item["title"]))


def _is_unique_seed_source_url(source_url: str) -> bool:
    return (
        "sillok.history.go.kr/id/" in source_url
        or "contents.history.go.kr/front/nh/view.do?levelId=" in source_url
    )


def _load_seed_documents() -> list[dict[str, str]]:
    documents = []
    for path in sorted(RAG_SEED_DIR.rglob("*.md")):
        parsed = _parse_seed_markdown(path)
        if parsed is not None:
            documents.append(parsed)
    return documents


def _parse_seed_markdown(path: Path) -> dict[str, str] | None:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", raw, re.S)
    if not match:
        return None

    metadata = {}
    for line in match.group("meta").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')

    title = metadata.get("title") or path.stem.replace("-", " ")
    body = _strip_original_section(match.group("body").strip())
    body = _normalize_for_rag_content(
        body,
        title=title,
        metadata=metadata,
    )
    return {
        "title": title,
        "period": metadata.get("period", ""),
        "source_url": metadata.get("source_url", ""),
        "content": body,
    }


def _strip_original_section(content: str) -> str:
    return re.split(r"\n## 원문\n", content, maxsplit=1)[0].strip()


def _normalize_for_rag_content(
    content: str,
    title: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    normalized = unescape(content)
    normalized = normalized.replace("\u3000", " ")
    normalized = re.sub(r"\b\d{1,4}\)", " ", normalized)
    normalized = _add_hanja_aliases(normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _add_hanja_aliases(text: str) -> str:
    for hanja, korean_alias in sorted(RAG_HANJA_ALIASES, key=lambda item: len(item[0]), reverse=True):
        text = _add_hanja_alias(text, hanja, korean_alias)
    return text


def _add_hanja_alias(text: str, hanja: str, korean_alias: str) -> str:
    def replace_once(match: re.Match[str]) -> str:
        context = text[max(0, match.start() - 24) : match.start()]
        aliases = [alias for alias in re.split(r"[/·,\s]+", korean_alias) if alias]
        if any(alias in context for alias in aliases):
            return hanja
        return f"{korean_alias}({hanja})"

    return re.sub(re.escape(hanja), replace_once, text)


def _chunk_seed_content(content: str) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        next_chunk = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current and len(next_chunk) > 800:
            chunks.append(current)
            current = paragraph
        else:
            current = next_chunk
    if current:
        chunks.append(current)
    return chunks


def _ensure_chunk_embeddings(db: Session, settings: Settings) -> None:
    chunks = db.scalars(select(RagChunk).where(RagChunk.embedding_json.is_(None))).all()
    for chunk, embedding in zip(chunks, _embed_texts(settings, [chunk.content for chunk in chunks]), strict=True):
        chunk.embedding_json = json.dumps(embedding)
    if chunks:
        db.commit()


def _search_chunks_by_keyword(db: Session, query: str, top_k: int) -> list[RagCitation]:
    keywords = _query_keywords(query)
    required_matches = 2 if len(keywords) >= 2 else 1
    documents = {document.id: document for document in db.scalars(select(RagDocument)).all()}
    chunks = db.scalars(select(RagChunk)).all()

    scored = []
    for chunk in chunks:
        haystack = chunk.content + " " + documents[chunk.document_id].title
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score >= required_matches:
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
        score = _cosine_similarity(query_embedding, embedding)
        if score >= EMBEDDING_MIN_RELEVANCE:
            scored.append((score, chunk))
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
        key = citation.source_url or citation.title
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


def _make_local_post_search_summary(
    title: str,
    content: str,
    post_type: str,
    category: str,
    tags: list[str],
) -> str:
    cleaned_content = re.sub(r"```[\s\S]*?```", " ", content)
    cleaned_content = re.sub(r"`([^`]+)`", r"\1", cleaned_content)
    cleaned_content = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", cleaned_content)
    cleaned_content = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", cleaned_content)
    cleaned_content = re.sub(r"[#>*_~|-]", " ", cleaned_content)
    cleaned_content = re.sub(r"\s+", " ", cleaned_content).strip()
    return (
        f"제목: {title}\n"
        f"글 유형: {post_type}\n"
        f"카테고리: {category}\n"
        f"태그: {', '.join(tags) if tags else '없음'}\n"
        f"본문 요약: {cleaned_content[:700]}"
    ).strip()


def _generate_text(settings: Settings, prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_llm_model,
        input=prompt,
    )
    return response.output_text


def _embed_text(settings: Settings, text: str) -> list[float]:
    embeddings = _make_langchain_embeddings(settings)
    return embeddings.embed_query(text)


def _embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    embeddings = _make_langchain_embeddings(settings)
    return embeddings.embed_documents(texts)


def _make_langchain_embeddings(settings: Settings):
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )


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
    normalized = (
        query.replace("#", " ")
        .replace("의", " ")
        .replace("와", " ")
        .replace("과", " ")
        .replace(",", " ")
    )
    seen: set[str] = set()
    keywords: list[str] = []
    for term in KNOWN_RAG_TERMS:
        if term in query and term not in seen:
            seen.add(term)
            keywords.append(term)
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
