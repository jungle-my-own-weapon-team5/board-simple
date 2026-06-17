from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path

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
    RagCorpusMode,
    RagQualityAgentResponse,
    RagQualityAttempt,
    RagCitation,
    RagSearchResponse,
    ToolLog,
)
from app.services.ai_demo import (
    get_discussion_topics as get_demo_discussion_topics,
    run_agent as run_demo_agent,
    search_external as search_demo_external,
    search_rag as search_demo_rag,
)
from app.services.cache import get_json_cache, make_cache_key, set_json_cache
from app.services.safety import agent_response_from_safety, moderate_input

RAG_SEED_DIR = Path(__file__).resolve().parents[2] / "rag_seed"
_SYNCED_SEED_BINDS: set[int] = set()
EMBEDDING_MIN_RELEVANCE = 0.45
OVERVIEW_CORPUS = "encykorea"
LEGACY_CORPUS_LABEL = "legacy"
PRIMARY_SOURCE_QUERY_TERMS = [
    "실록",
    "원문",
    "사료",
    "기록",
    "국역",
    "원전",
    "왕이",
    "교지",
]
PRIMARY_SOURCE_RECONSTRUCTION_TERMS = [
    "사건",
    "일화",
    "경위",
    "정황",
    "인과관계",
    "어떻게",
    "왜",
]
CATEGORY_GROUP_RULES = [
    ("royal_family", ["왕실-", "국왕", "종친", "비빈", "궁중", "행행", "사급", "종사", "의식"]),
    ("appointment", ["인사-", "임면", "관리", "선발", "관직"]),
    ("judicial", ["사법-", "탄핵", "행형", "법제", "재판", "송사"]),
    ("social_status", ["사회-", "신분", "노비", "가족", "향촌"]),
    ("economy", ["재정-", "상공", "전세", "공물", "호구", "농업", "토지"]),
    ("diplomacy", ["외교-", "명(", "왜(", "야인", "여진", "청("]),
    ("military", ["군사-", "군정", "관방", "병법", "훈련"]),
    ("astronomy_weather", ["과학-천기", "천기", "재이", "역법"]),
    ("thought_religion", ["사상-", "불교", "유학", "토속신앙"]),
    ("historiography", ["역사-", "고사", "전사", "편사"]),
    ("publication", ["출판-", "서책", "문서"]),
]
CATEGORY_QUERY_HINTS = [
    (
        "royal_family",
        ["왕", "임금", "왕실", "공주", "대군", "군", "후궁", "궁녀", "세자", "왕비", "총애", "하가", "혼인", "생애", "인물", "관계", "일화"],
    ),
    ("appointment", ["관직", "임명", "승진", "제수", "파직", "인사", "벼슬", "등용"]),
    ("judicial", ["탄핵", "처벌", "죄", "주살", "폐출", "송사", "재판", "옥사", "사건"]),
    ("social_status", ["노비", "가비", "여종", "신분", "백성", "생활", "가노", "비"]),
    ("economy", ["토지", "전세", "공물", "상업", "시장", "집", "노비문권", "재산"]),
    ("diplomacy", ["외교", "명나라", "왜", "일본", "여진", "사신", "조공"]),
    ("military", ["전쟁", "군사", "전투", "의병", "왜란", "호란", "군대"]),
    ("astronomy_weather", ["천문", "날씨", "가뭄", "비", "일식", "월식", "재이"]),
    ("thought_religion", ["불교", "유교", "성리학", "신앙", "제사", "사상"]),
    ("historiography", ["편찬", "기록", "사관", "실록", "역사서"]),
    ("publication", ["책", "문서", "서책", "출판", "원문", "국역"]),
]
CATEGORY_AVOID_GROUPS = {
    "royal_family": {"astronomy_weather", "diplomacy", "military"},
    "appointment": {"astronomy_weather"},
    "judicial": {"astronomy_weather", "diplomacy"},
    "social_status": {"astronomy_weather", "diplomacy"},
    "economy": {"astronomy_weather"},
    "diplomacy": {"astronomy_weather"},
    "military": {"astronomy_weather"},
}

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

QUERY_REQUEST_STOP_TERMS = {
    "알려줘",
    "알려주세요",
    "소개해줘",
    "소개해주세요",
    "정리해줘",
    "정리해주세요",
    "설명해줘",
    "설명해주세요",
    "써줘",
    "작성해줘",
    "누구",
    "무엇",
    "뭐",
    "어떤",
    "몇",
    "명",
    "가지",
    "대표",
    "대표적",
    "대표적인",
    "활약",
    "활약한",
    "관련",
    "대해",
    "대해서",
}
QUERY_PARTICLE_SUFFIXES = [
    "으로부터",
    "로부터",
    "에게서",
    "에서",
    "에게",
    "으로",
    "까지",
    "부터",
    "처럼",
    "보다",
    "하고",
    "하며",
    "이나",
    "나",
    "이나마",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "와",
    "과",
    "로",
]
COUNT_REQUEST_PATTERN = re.compile(r"^\d+(명|개|가지|건|편|명만)?$")
PERSON_LIST_TERMS = {"인물", "사람", "왕", "왕비", "공주", "대군", "신하", "장수", "장군", "의병", "승병", "학자"}

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


def search_rag(
    db: Session,
    settings: Settings,
    query: str,
    top_k: int,
    corpus: RagCorpusMode = "auto",
) -> RagSearchResponse:
    try:
        _ensure_seed_documents(db)
        corpus_priority = _rag_corpus_priority(query, corpus)
        searched_corpora = [_public_corpus_name(item) for item in corpus_priority]
        cache_key = make_cache_key(
            "rag_search:v1",
            {
                "query": query,
                "top_k": top_k,
                "corpus": corpus,
                "corpus_priority": searched_corpora,
                "embedding_model": settings.openai_embedding_model if settings.openai_api_key else "keyword",
                "summary_model": settings.openai_llm_model if settings.openai_api_key else "local",
            },
        )
        cached = get_json_cache(settings, cache_key)
        if cached is not None:
            return RagSearchResponse.model_validate(cached)

        if settings.openai_api_key:
            query_embedding = _embed_text(settings, query)
            citations = _search_by_corpus_priority(
                lambda target_corpus: _search_chunks_by_embedding(db, query_embedding, query, top_k, target_corpus),
                corpus_priority,
            )
            if not citations:
                citations = _search_by_corpus_priority(
                    lambda target_corpus: _search_chunks_by_keyword(db, query, top_k, target_corpus),
                    corpus_priority,
                )
        else:
            citations = _search_by_corpus_priority(
                lambda target_corpus: _search_chunks_by_keyword(db, query, top_k, target_corpus),
                corpus_priority,
            )
        if not citations:
            response = RagSearchResponse(
                answer_summary=(
                    f"`{query}` 주제와 직접 연결되는 내부 RAG seed 근거를 찾지 못했습니다. "
                    "외부 자료 링크를 확인하거나 seed 문서를 추가해야 합니다."
                ),
                citations=[],
                weak_evidence=True,
                searched_corpora=searched_corpora,
            )
            set_json_cache(settings, cache_key, response.model_dump(mode="json"), settings.rag_cache_ttl_seconds)
            return response

        summary = _make_rag_summary(settings, query, citations)
        _save_ai_response(db, "rag_search", query, summary, settings.openai_llm_model if settings.openai_api_key else "local")
        response = RagSearchResponse(
            answer_summary=summary,
            citations=citations,
            weak_evidence=len(citations) < 2,
            searched_corpora=searched_corpora,
        )
        set_json_cache(settings, cache_key, response.model_dump(mode="json"), settings.rag_cache_ttl_seconds)
        return response
    except Exception:
        return search_demo_rag(query, top_k)


def run_rag_quality_agent(
    db: Session,
    settings: Settings,
    query: str,
    top_k: int,
    corpus: RagCorpusMode = "auto",
) -> RagQualityAgentResponse:
    agent_steps = [
        AgentStep(name="intent", output="RAG 결과 품질을 높이기 위해 원 질의 검색과 재작성 검색을 계획했습니다."),
    ]
    searched_corpora = [_public_corpus_name(item) for item in _rag_corpus_priority(query, corpus)]
    candidate_queries = _build_rag_agent_queries(settings, query)
    attempts: list[RagQualityAttempt] = []
    collected_citations: list[RagCitation] = []
    best_query = candidate_queries[0]
    best_result: RagSearchResponse | None = None
    best_score = -1.0

    for index, candidate_query in enumerate(candidate_queries, start=1):
        result = search_rag(db, settings, candidate_query, top_k, corpus)
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
        best_result = search_rag(db, settings, query, top_k, corpus)

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
        searched_corpora=searched_corpora,
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


def search_external(db: Session, keyword: str, settings: Settings | None = None) -> ExternalSearchResponse:
    from app.services import mcp_server

    started = time.perf_counter()
    search_error = False
    query_candidates = _external_query_candidates(settings, keyword)
    try:
        raw_resources = _search_external_candidates(mcp_server, keyword, query_candidates)
        clue_queries = _external_clue_queries(keyword, raw_resources)
        if clue_queries:
            raw_resources = _merge_external_raw_resources(
                keyword,
                raw_resources,
                _search_external_candidates(mcp_server, keyword, clue_queries),
            )
    except Exception:
        search_error = True
        raw_resources = []
    resources = [
        ExternalResource(
            title=str(item.get("title") or ""),
            provider=str(item.get("provider") or "국사편찬위원회 조선왕조실록"),
            url=str(item.get("url") or ""),
            description=str(item.get("description") or "조선왕조실록 검색 결과에서 조회한 기사입니다."),
            source_type=str(item.get("source_type") or ""),
            result_type=str(item.get("result_type") or ""),
            verification_status=str(item.get("verification_status") or ""),
            content_excerpt=str(item.get("content_excerpt") or "") or None,
            confidence=float(item.get("confidence") or 0.0),
            can_quote=str(item.get("can_quote") or "").lower() == "true" or item.get("can_quote") is True,
        )
        for item in raw_resources
        if str(item.get("url") or "").startswith(("http://", "https://"))
    ]
    verified_count = sum(1 for item in raw_resources if item.get("result_type") == "verified")
    link_count = sum(1 for item in raw_resources if item.get("result_type") == "search_link")
    if verified_count:
        status = "ok"
        description = f"외부 자료 provider에서 확인된 자료 {verified_count}건과 검색 링크 {link_count}건을 확인했습니다."
    elif link_count:
        status = "link_ready"
        description = f"확인된 자료는 없지만 추가 확인용 검색 링크 {link_count}건을 제공했습니다."
    elif search_error:
        status = "error"
        description = "외부 검색 provider 호출에 실패했습니다. 외부 자료 링크를 제공하지 않습니다."
    else:
        status = "no_results"
        description = "외부 검색 provider에서 결과를 확인하지 못했습니다. 외부 자료 링크를 제공하지 않습니다."

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    tool_log = ToolLog(
        tool="history.search",
        input=" | ".join(query_candidates[:6]) or keyword,
        status=status,
        elapsed_ms=elapsed_ms,
    )
    _save_tool_log(db, tool_log, description)
    return ExternalSearchResponse(
        resources=resources,
        tool_log=tool_log,
    )


def _search_external_candidates(mcp_server, original_keyword: str, candidates: list[str]) -> list[dict[str, str]]:
    raw_resources: list[dict[str, str]] = []
    primary_candidates = candidates[:4]
    with ThreadPoolExecutor(max_workers=max(1, len(primary_candidates))) as executor:
        futures = {
            executor.submit(mcp_server.search_history_providers, candidate, ["sillok"]): candidate
            for candidate in primary_candidates
        }
        for future, candidate in futures.items():
            try:
                found_items = future.result()
            except Exception:
                found_items = []
            for item in found_items:
                raw_resources.append(_external_resource_with_planner_score(original_keyword, candidate, item))

    if any(item.get("verification_status") == "primary_verified" for item in raw_resources):
        return _rank_external_raw_resources(original_keyword, raw_resources)

    for candidate in candidates[:1]:
        for item in mcp_server.search_history_providers(candidate, _external_secondary_providers(candidate)):
            raw_resources.append(
                _external_resource_with_planner_score(original_keyword, candidate, item)
            )
    return _rank_external_raw_resources(original_keyword, raw_resources)


def _external_resource_with_planner_score(
    original_keyword: str,
    candidate: str,
    item: dict[str, str],
) -> dict[str, str]:
    return {
        **item,
        "planner_query": candidate,
        "relevance_score": str(
            float(item.get("relevance_score") or 0)
            + _planner_query_bonus(original_keyword, candidate, item)
        ),
    }


def _merge_external_raw_resources(
    original_keyword: str,
    first: list[dict[str, str]],
    second: list[dict[str, str]],
) -> list[dict[str, str]]:
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for item in [*first, *second]:
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(item)
    return _rank_external_raw_resources(original_keyword, merged)


def _rank_external_raw_resources(original_keyword: str, resources: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in sorted(resources, key=lambda resource: _external_resource_rank_key(original_keyword, resource), reverse=True):
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(item)
    return unique[:12]


def _external_resource_rank_key(original_keyword: str, resource: dict[str, str]) -> tuple[float, float, float, float, float, float]:
    planner_query = str(resource.get("planner_query") or resource.get("matched_query") or "")
    haystack = " ".join(
        str(resource.get(key) or "")
        for key in ["title", "description", "content_excerpt"]
    )
    planner_terms = _query_keywords(planner_query)
    original_terms = _query_keywords(original_keyword)
    planner_matches = sum(1 for term in planner_terms if term in haystack)
    planner_ratio = planner_matches / max(1, len(planner_terms))
    specificity = min(1.0, len(planner_terms) / 5)
    original_matches = sum(1 for term in original_terms if term in haystack)
    original_ratio = original_matches / max(1, len(original_terms))
    primary = 1.0 if str(resource.get("verification_status") or "") == "primary_verified" else 0.0
    verified = 1.0 if str(resource.get("result_type") or "") == "verified" else 0.0
    score = float(resource.get("relevance_score") or 0)
    return (primary, verified, planner_ratio, specificity, original_ratio, score)


def _external_secondary_providers(candidate: str) -> list[str]:
    compact = candidate.replace(" ", "")
    if any(term in compact for term in ["어찰", "편지", "서찰", "고문서", "문집", "원문"]):
        return ["kostma", "nlk", "encykorea", "web"]
    if any(term in compact for term in ["복식", "유물", "소장품", "그림", "초상", "어진", "이미지"]):
        return ["museum", "encykorea", "web"]
    return ["encykorea", "web"]


def _planner_query_bonus(original_keyword: str, candidate: str, item: dict[str, str]) -> float:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ["title", "description", "content_excerpt", "matched_query", "planner_query"]
    )
    bonus = 0.0
    for term in _query_keywords(original_keyword):
        if term in candidate:
            bonus += 0.08
        if term in haystack:
            bonus += 0.08
    if str(item.get("verification_status") or "") == "primary_verified":
        bonus += 0.25
    if candidate.strip() != original_keyword.strip():
        bonus += 0.25
    for term in _query_keywords(candidate):
        if term in haystack:
            bonus += 0.18
        else:
            bonus -= 0.45
    return bonus


def _external_query_candidates(settings: Settings | None, query: str) -> list[str]:
    local_queries = _local_external_query_candidates(query)
    if not settings or not settings.openai_api_key:
        return local_queries

    cache_key = make_cache_key(
        "external_query_planner:v1",
        {
            "query": query,
            "model": settings.openai_llm_model,
        },
    )
    cached = get_json_cache(settings, cache_key)
    if isinstance(cached, list):
        cached_queries = [str(item).strip() for item in cached if str(item).strip()]
        return _dedupe_query_candidates([*cached_queries, *local_queries])[:8]

    prompt = (
        "너는 답변자가 아니라 한국사 자료 검색 query planner다. "
        "사용자 질문은 현대어, 별칭, 후대 표현일 수 있다. "
        "조선시대 자료에는 당시 지위명, 책봉명, 한자명, 사건명, 제도명으로 기록될 수 있다. "
        "사실을 단정하지 말고 검색 후보만 만들어라. "
        "사용자 원문 후보 1개, 당시 표현/지위명 후보, 한자어 후보, 더 넓은 상위 개념 후보를 포함한다. "
        "JSON만 반환한다. 스키마: {\"queries\":[\"\"]}. 최대 8개.\n"
        f"사용자 질문: {query}"
    )
    try:
        payload = _extract_json(_generate_text(settings, prompt))
        llm_queries = [str(item).strip() for item in payload.get("queries", []) if str(item).strip()]
        candidates = _dedupe_query_candidates([*llm_queries, *local_queries])[:8]
        set_json_cache(settings, cache_key, candidates, settings.rag_cache_ttl_seconds)
        return candidates
    except Exception:
        return local_queries


def _local_external_query_candidates(query: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", query).strip()
    compact = cleaned.replace(" ", "")
    noun_terms = _extract_query_noun_terms(cleaned)
    normalized_query = " ".join(noun_terms) if noun_terms else cleaned
    candidates = [normalized_query]
    keywords = _query_keywords(normalized_query)
    if keywords:
        candidates.append(keywords[0])
        candidates.append(" ".join(keywords[:5]))
    if len(keywords) >= 2:
        candidates.append(f"{keywords[0]} {keywords[1]}")
    candidates.extend(_expand_query_by_question_type(cleaned, noun_terms))

    return _dedupe_query_candidates(candidates)[:8]


def _expand_query_by_question_type(original_query: str, noun_terms: list[str]) -> list[str]:
    if not noun_terms:
        return []
    compact = original_query.replace(" ", "")
    base = " ".join(noun_terms[:4])
    expansions: list[str] = []
    asks_for_representative_list = (
        bool(re.search(r"\d+\s*(명|개|가지|건|편)", original_query))
        or any(term in compact for term in ["대표", "꼽", "추천", "몇명", "세명", "3명"])
    )
    has_person_topic = any(term in base for term in PERSON_LIST_TERMS)
    if asks_for_representative_list:
        expansions.append(f"{base} 대표")
        expansions.append(f"{base} 대표 사례")
        if has_person_topic:
            expansions.append(f"{base} 대표 인물")
            expansions.append(f"{base} 인물")
    if any(term in compact for term in ["개괄", "요약", "정리", "설명", "뜻", "의미"]):
        expansions.append(f"{base} 개괄")
        expansions.append(f"{base} 설명")
    return expansions


def _external_clue_queries(original_query: str, resources: list[dict[str, str]]) -> list[str]:
    if not resources:
        return []
    text = " ".join(
        str(resource.get(key) or "")
        for resource in resources[:6]
        for key in ["title", "description", "content_excerpt"]
    )
    clues: list[str] = []
    base_terms = _query_keywords(original_query)[:2]
    subject = base_terms[0] if base_terms else ""
    for match in re.findall(r"([가-힣]{2,5})\([^)]+\)", text):
        clue = match.strip()
        if _valid_external_clue(clue, original_query, subject):
            clues.append(clue)
    patterns = [
        r"[가-힣]{2,6}\s?대군",
        r"[가-힣]{2,6}\s?공주",
        r"[가-힣]{2,6}\s?옹주",
        r"[가-힣]{2,6}\s?왕후",
        r"[가-힣]{1,4}\s?빈\s?[가-힣]씨",
        r"[가-힣]{1,4}빈\s?[가-힣]씨",
        r"[가-힣]{2,4}\s?김씨",
        r"[가-힣]{2,5}술",
        r"[가-힣]{2,6}폐출",
        r"[가-힣]{2,4}\s?고양이",
        r"[가-힣]{2,5}위",
        r"[가-힣]{2,5}군",
        r"[가-힣]{2,5}부원군",
        r"[가-힣]{2,5}\s?정씨",
        r"[가-힣]{2,4}수",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            clue = re.sub(r"\s+", " ", match).strip()
            if _valid_external_clue(clue, original_query, subject):
                clues.append(clue)
    candidates: list[str] = []
    for clue in _dedupe_query_candidates(clues)[:6]:
        if subject:
            candidates.append(f"{subject} {clue}")
        else:
            candidates.append(clue)
    return _dedupe_query_candidates(candidates)[:6]


def _valid_external_clue(clue: str, original_query: str, subject: str) -> bool:
    compact = clue.replace(" ", "")
    if len(compact) < 2:
        return False
    if compact in original_query.replace(" ", ""):
        return False
    if subject and compact == subject.replace(" ", ""):
        return False
    if compact in _generic_external_clues():
        return False
    if "되니" in compact or "하니" in compact or "하며" in compact:
        return False
    if len(compact) > 5 and not compact.endswith(("대군", "공주", "옹주", "왕후", "부원군")):
        return False
    return True


def _generic_external_clues() -> set[str]:
    return {
        "공주",
        "옹주",
        "대군",
        "왕후",
        "임금",
        "전하",
        "세자",
        "문무",
        "신하",
        "사신",
    }


def run_agent(db: Session, settings: Settings, goal: str, topic: str) -> AgentRunResponse:
    safety_response = agent_response_from_safety(moderate_input(topic, surface="agent", require_history_topic=False))
    if safety_response is not None:
        return safety_response
    safety_response = agent_response_from_safety(moderate_input(topic, surface="agent"))
    if safety_response is not None:
        return safety_response

    try:
        rag = search_rag(db, settings, topic, 3)
        external = search_external(db, topic, settings)
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
                source_type=item["source_type"],
                corpus=item["corpus"],
                metadata_json=item["metadata_json"],
            )
            db.add(document)
            db.flush()
        else:
            document = existing
            document.period = item["period"]
            document.source_url = item["source_url"]
            document.source_type = item["source_type"]
            document.corpus = item["corpus"]
            document.metadata_json = item["metadata_json"]

        current_chunks = db.scalars(
            select(RagChunk)
            .where(RagChunk.document_id == document.id)
            .order_by(RagChunk.chunk_index)
        ).all()
        next_chunks = _chunk_seed_content(item["content"], item["source_type"])
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
        or "encykorea.aks.ac.kr/Article/" in source_url
    )


def _rag_corpus_priority(query: str, corpus: RagCorpusMode = "auto") -> list[str | None]:
    if corpus == "all":
        return [None]
    if corpus == LEGACY_CORPUS_LABEL:
        return [""]
    if corpus != "auto":
        return [corpus]
    if any(term in query for term in PRIMARY_SOURCE_QUERY_TERMS):
        return ["", OVERVIEW_CORPUS]
    if _looks_like_primary_source_reconstruction(query):
        return ["", OVERVIEW_CORPUS]
    return [OVERVIEW_CORPUS, ""]


def _looks_like_primary_source_reconstruction(query: str) -> bool:
    compact = query.replace(" ", "")
    if not any(term in compact for term in PRIMARY_SOURCE_RECONSTRUCTION_TERMS):
        return False
    keywords = _query_keywords(query)
    has_specific_subject = any(
        len(keyword) >= 3
        and keyword not in PRIMARY_SOURCE_RECONSTRUCTION_TERMS
        and keyword not in {"어떻게", "무엇", "어떤", "대해", "관계"}
        for keyword in keywords
    )
    return has_specific_subject


def _public_corpus_name(corpus: str | None) -> str:
    if corpus is None:
        return "all"
    if corpus == "":
        return LEGACY_CORPUS_LABEL
    return corpus


def _search_by_corpus_priority(search, corpus_priority: list[str | None]) -> list[RagCitation]:
    seen_corpora: set[str | None] = set()
    for corpus in corpus_priority:
        if corpus in seen_corpora:
            continue
        seen_corpora.add(corpus)
        citations = search(corpus)
        if citations:
            return citations
    return []


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
        "source_type": metadata.get("source_type", ""),
        "corpus": metadata.get("corpus", ""),
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
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


def _chunk_seed_content(content: str, source_type: str = "") -> list[str]:
    max_chars = 1400 if source_type == "overview" else 800
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        next_chunk = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current and len(next_chunk) > max_chars:
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


def _search_chunks_by_keyword(
    db: Session,
    query: str,
    top_k: int,
    corpus: str | None = None,
) -> list[RagCitation]:
    keywords = _query_keywords(query)
    required_matches = 2 if len(keywords) >= 2 else 1
    documents = _documents_by_corpus(db, corpus)
    if not documents:
        return []
    chunks = db.scalars(select(RagChunk).where(RagChunk.document_id.in_(list(documents)))).all()

    scored = []
    for chunk in chunks:
        document = documents[chunk.document_id]
        haystack = chunk.content + " " + document.title
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score >= required_matches:
            metadata_score = _metadata_relevance_boost(query, document)
            scored.append((score + metadata_score, score, metadata_score, chunk))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    return _dedupe_citations(
        [
            _citation_from_chunk(
                documents[chunk.document_id],
                chunk,
                max(0.0, min(1.0, 0.5 + min(raw_score, 5) * 0.1 + metadata_score)),
            )
            for _rank_score, raw_score, metadata_score, chunk in scored
        ],
        top_k,
    )


def _search_chunks_by_embedding(
    db: Session,
    query_embedding: list[float],
    query: str,
    top_k: int,
    corpus: str | None = None,
) -> list[RagCitation]:
    documents = _documents_by_corpus(db, corpus)
    if not documents:
        return []
    chunks = db.scalars(
        select(RagChunk)
        .where(RagChunk.document_id.in_(list(documents)))
        .where(RagChunk.embedding_json.is_not(None))
    ).all()
    scored = []
    for chunk in chunks:
        embedding = json.loads(chunk.embedding_json or "[]")
        document = documents[chunk.document_id]
        score = _cosine_similarity(query_embedding, embedding) + _metadata_relevance_boost(query, document)
        score = min(score, 1.0)
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


def _documents_by_corpus(db: Session, corpus: str | None) -> dict[int, RagDocument]:
    statement = select(RagDocument)
    if corpus is not None:
        statement = statement.where(RagDocument.corpus == corpus)
    return {document.id: document for document in db.scalars(statement).all()}


def _metadata_relevance_boost(query: str, document: RagDocument) -> float:
    boost = 0.0
    normalized_query = re.sub(r"\s+", "", query)
    normalized_title = re.sub(r"\s+", "", document.title)
    if normalized_title and normalized_title in normalized_query:
        boost += 0.18

    metadata = {}
    if document.metadata_json:
        try:
            metadata = json.loads(document.metadata_json)
        except json.JSONDecodeError:
            metadata = {}
    keywords = str(metadata.get("keywords", ""))
    if keywords and any(keyword.strip() and keyword.strip() in query for keyword in keywords.split(",")):
        boost += 0.08
    boost += _category_relevance_adjustment(query, metadata)
    return round(boost, 3)


def _category_relevance_adjustment(query: str, metadata: dict[str, object]) -> float:
    document_groups = _metadata_category_groups(metadata)
    if not document_groups:
        return 0.0
    preferred_groups = _query_category_groups(query)
    if not preferred_groups:
        return 0.0

    matched = document_groups & preferred_groups
    avoid_groups = set().union(*(CATEGORY_AVOID_GROUPS.get(group, set()) for group in preferred_groups))
    avoided = document_groups & avoid_groups
    adjustment = min(0.12, 0.06 * len(matched))
    if avoided and not matched:
        adjustment -= min(0.06, 0.03 * len(avoided))
    return adjustment


def _metadata_category_groups(metadata: dict[str, object]) -> set[str]:
    raw_categories = str(metadata.get("categories") or metadata.get("category") or "")
    groups: set[str] = set()
    for group, markers in CATEGORY_GROUP_RULES:
        if any(marker in raw_categories for marker in markers):
            groups.add(group)
    return groups


def _query_category_groups(query: str) -> set[str]:
    compact = query.replace(" ", "")
    groups: set[str] = set()
    for group, hints in CATEGORY_QUERY_HINTS:
        if any(hint in query or hint in compact for hint in hints):
            groups.add(group)
    return groups


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


def _generate_text(settings: Settings, prompt: str, model: str | None = None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=model or settings.openai_llm_model,
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
    normalized = re.sub(r"[#,?!.~,;:()\[\]{}]", " ", query)
    seen: set[str] = set()
    keywords: list[str] = []
    for term in KNOWN_RAG_TERMS:
        if term in query and term not in seen:
            seen.add(term)
            keywords.append(term)
    for word in _extract_query_noun_terms(normalized):
        if len(word) >= 2 and word not in seen:
            seen.add(word)
            keywords.append(word)
    return keywords


def _extract_query_noun_terms(query: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-z가-힣一-龥]+", query)
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        term = _normalize_query_token(token)
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _normalize_query_token(token: str) -> str:
    term = token.strip().strip("_-")
    if not term:
        return ""
    if COUNT_REQUEST_PATTERN.match(term):
        return ""
    for suffix in QUERY_PARTICLE_SUFFIXES:
        if len(term) > len(suffix) + 1 and term.endswith(suffix):
            term = term[: -len(suffix)]
            break
    if term.endswith("한") and len(term) > 2 and term[:-1] in QUERY_REQUEST_STOP_TERMS:
        term = term[:-1]
    if term in QUERY_REQUEST_STOP_TERMS:
        return ""
    if len(term) < 2:
        return ""
    return term


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
    if db is None:
        return
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
