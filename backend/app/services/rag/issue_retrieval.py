"""LLM 쟁점 계획을 먼저 수행한 뒤 쟁점별 RAG 검색을 조율합니다."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.embedding import EmbeddingProfile
from app.models.rag_run import RagRetrieval
from app.repositories import embeddings as embedding_repository
from app.repositories import rag_runs as rag_run_repository
from app.services.ai.client import AIClient
from app.services.ai.errors import ProviderError
from app.services.ai.types import AITextRequest
from app.services.rag.chunking import (
    has_article_boundary_contamination,
    is_title_only_article_chunk,
)
from app.services.rag.legal_open_api import LawOpenApiClient, LawOpenApiError
from app.services.rag.legal_open_api_sync import sync_and_embed_law_open_api_statute
from app.services.rag.legal_source_planner import (
    ExpectedArticleRef,
    LegalSourceCandidate,
    LegalSourcePlan,
    PlannedLegalIssue,
    plan_legal_source_candidates,
)
from app.services.rag.retrieval import (
    RagSearchResultItem,
    SearchLegalDocumentsResult,
    search_legal_documents,
)


@dataclass(frozen=True)
class _SupplementalRetrievalRequest:
    query: str
    expected_article_ref: ExpectedArticleRef | None = None


@dataclass(frozen=True)
class _EvidenceReviewResult:
    keep_chunk_ids: list[int]
    supplemental_queries: list[str]
    missing_article_refs: list[ExpectedArticleRef]


def search_legal_documents_by_planned_issues(
    db: Session,
    *,
    user_id: int,
    facts: str,
    question: str,
    embedding_profile: EmbeddingProfile,
    ai_client: AIClient,
    settings: Settings,
    search_mode: str,
    top_k: int | None,
    score_threshold: float | None,
    max_chunks_per_document: int | None,
    prompt_version: str,
    timeout_seconds: int,
    document_types: list[str] | None = None,
    sync_official_sources: bool = True,
) -> SearchLegalDocumentsResult:
    """사용자 입력을 쟁점별 query로 분해하고 각 쟁점마다 top-k 검색을 실행합니다."""

    original_query = _combined_query(facts=facts, question=question)
    # planner 결과는 검색 계획일 뿐이며, 답변의 citation 근거로 직접 쓰지 않습니다.
    plan = plan_legal_source_candidates(
        ai_client=ai_client,
        settings=settings,
        facts=facts,
        question=question,
        search_mode=search_mode,
        max_candidates=settings.ai_source_planner_max_candidates,
    )
    issues = _issues_or_default(plan, original_query)
    if sync_official_sources:
        # API endpoint에서는 사용자 요청 기반 공식 법령 보강을 허용합니다.
        # MCP 내부 RAG tool은 Agent action 경계를 지키기 위해 이 옵션을 끌 수 있습니다.
        _sync_official_sources_for_plan(
            db,
            plan=plan,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            settings=settings,
            document_types=document_types,
            timeout_seconds=timeout_seconds,
        )

    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]] = []
    for issue in issues:
        # top_k는 전체 사실관계 1개가 아니라 각 planned issue query마다 적용됩니다.
        result = search_legal_documents(
            db,
            user_id=user_id,
            query=issue.internal_rag_query,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            search_mode=search_mode,
            top_k=top_k,
            score_threshold=score_threshold,
            max_chunks_per_document=max_chunks_per_document,
            prompt_version=prompt_version,
            timeout_seconds=timeout_seconds,
            document_types=document_types,
        )
        if result.status == "failed":
            return result
        issue_results.append((issue, result))

    if _llm_evidence_review_enabled(ai_client=ai_client, settings=settings):
        issue_results = _append_keyword_hint_results(
            db,
            issue_results=issue_results,
            embedding_profile=embedding_profile,
            document_types=document_types,
        )
    issue_results = _review_and_supplement_issue_results(
        db,
        user_id=user_id,
        facts=facts,
        question=question,
        issue_results=issue_results,
        embedding_profile=embedding_profile,
        ai_client=ai_client,
        settings=settings,
        search_mode=search_mode,
        score_threshold=score_threshold,
        max_chunks_per_document=max_chunks_per_document,
        prompt_version=prompt_version,
        timeout_seconds=timeout_seconds,
        document_types=document_types,
    )
    result = _merge_issue_results(
        db,
        original_query=original_query,
        issue_results=issue_results,
    )
    db.commit()
    return result


def _append_keyword_hint_results(
    db: Session,
    *,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
    embedding_profile: EmbeddingProfile,
    document_types: list[str] | None,
) -> list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]]:
    """Planned issue query의 핵심 단어로 조문 heading 후보를 보강합니다."""

    if not issue_results:
        return issue_results

    searchable_embeddings = embedding_repository.list_searchable_chunk_embeddings(
        db,
        embedding_profile.id,
        document_types=document_types,
    )
    if not searchable_embeddings:
        return issue_results

    existing_chunk_ids = {
        item.chunk_id for _issue, result in issue_results for item in result.results
    }
    updated_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]] = []
    for issue, result in issue_results:
        keyword_items: list[RagSearchResultItem] = []
        for chunk_embedding, keyword_score in _keyword_heading_matches(
            searchable_embeddings,
            query=issue.internal_rag_query,
            limit=12,
        ):
            if len(keyword_items) >= 4:
                break
            if chunk_embedding.chunk_id in existing_chunk_ids:
                continue
            if _chunk_embedding_is_invalid(chunk_embedding):
                continue
            keyword_items.append(
                _keyword_hint_result_item(
                    chunk_embedding=chunk_embedding,
                    keyword_score=keyword_score,
                )
            )
            existing_chunk_ids.add(chunk_embedding.chunk_id)
        if keyword_items:
            updated_results.append(
                (
                    issue,
                    replace(result, results=[*result.results, *keyword_items]),
                )
            )
        else:
            updated_results.append((issue, result))
    return updated_results


def _append_coverage_anchor_results(
    db: Session,
    *,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
    embedding_profile: EmbeddingProfile,
    document_types: list[str] | None,
) -> list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]]:
    """Reviewer가 놓치기 쉬운 핵심 표제어 chunk를 최종 후보에 보강합니다."""

    if not issue_results:
        return issue_results
    searchable_embeddings = embedding_repository.list_searchable_chunk_embeddings(
        db,
        embedding_profile.id,
        document_types=document_types,
    )
    if not searchable_embeddings:
        return issue_results

    existing_chunk_ids = {
        item.chunk_id for _issue, result in issue_results for item in result.results
    }
    updated_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]] = []
    for issue, result in issue_results:
        anchor_items: list[RagSearchResultItem] = []
        for chunk_embedding in _coverage_anchor_matches(
            searchable_embeddings,
            query=issue.internal_rag_query,
        ):
            if chunk_embedding.chunk_id in existing_chunk_ids:
                continue
            if _chunk_embedding_is_invalid(chunk_embedding):
                continue
            anchor_items.append(_coverage_anchor_result_item(chunk_embedding=chunk_embedding))
            existing_chunk_ids.add(chunk_embedding.chunk_id)
            if len(anchor_items) >= 3:
                break
        if anchor_items:
            updated_results.append(
                (
                    issue,
                    replace(result, results=[*result.results, *anchor_items]),
                )
            )
        else:
            updated_results.append((issue, result))
    return updated_results


def _remove_semantic_false_positive_results(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]]:
    """사체 은닉과 범인 은닉처럼 표면 키워드만 비슷한 false positive를 제거합니다."""

    updated_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]] = []
    for issue, result in issue_results:
        filtered_items = [
            item
            for item in result.results
            if not _is_invalid_retrieval_item(item)
            and not _is_semantic_false_positive(item, issue=issue)
        ]
        updated_results.append((issue, replace(result, results=filtered_items)))
    return updated_results


def _sync_official_sources_for_plan(
    db: Session,
    *,
    plan: LegalSourcePlan,
    embedding_profile: EmbeddingProfile,
    ai_client: AIClient,
    settings: Settings,
    document_types: list[str] | None,
    timeout_seconds: int,
) -> None:
    """계획된 공식 법령 후보를 요청 범위 안에서 동기화하고 embedding합니다."""

    if not settings.law_open_api_oc.strip():
        return
    if document_types is not None and "statute" not in document_types:
        return

    client = LawOpenApiClient(
        oc=settings.law_open_api_oc,
        base_url=settings.law_open_api_base_url,
        service_url=settings.law_open_api_service_url,
        timeout_seconds=settings.mcp_request_timeout_seconds,
    )
    for candidate in _statute_candidates(plan):
        try:
            sync_and_embed_law_open_api_statute(
                db,
                client=client,
                query=_official_source_sync_query(candidate),
                embedding_profile=embedding_profile,
                ai_client=ai_client,
                search_limit=_official_source_search_limit(settings),
                preferred_titles=_preferred_titles_for_candidate(candidate),
                timeout_seconds=timeout_seconds,
            )
        except LawOpenApiError:
            continue


def _merge_issue_results(
    db: Session,
    *,
    original_query: str,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> SearchLegalDocumentsResult:
    """여러 쟁점 검색 결과를 하나의 응답으로 병합합니다."""

    if not issue_results:
        raise ValueError("issue_results must not be empty")

    base_result = issue_results[0][1]
    merged_by_chunk_id: dict[int, RagSearchResultItem] = {}
    ordered_chunk_ids: list[int] = []
    for issue, result in issue_results:
        for item in result.results:
            tagged_item = _tag_item_with_issue(item, issue)
            existing_item = merged_by_chunk_id.get(item.chunk_id)
            if existing_item is None:
                merged_by_chunk_id[item.chunk_id] = tagged_item
                ordered_chunk_ids.append(item.chunk_id)
            else:
                # 같은 chunk가 여러 쟁점에서 잡히면 중복 노출하지 않고 쟁점 metadata만 누적합니다.
                merged_by_chunk_id[item.chunk_id] = _merge_duplicate_item(
                    existing_item,
                    tagged_item,
                )

    merged_items = [
        replace(merged_by_chunk_id[chunk_id], rank=index + 1)
        for index, chunk_id in enumerate(ordered_chunk_ids)
    ]
    merged_items = _prioritize_expected_article_items(merged_items)
    merged_items = [
        replace(item, rank=index + 1)
        for index, item in enumerate(merged_items)
    ]
    merged_items = _index_merged_retrievals_for_base_run(
        db,
        base_result=base_result,
        merged_items=merged_items,
    )
    return replace(
        base_result,
        query=original_query,
        results=merged_items,
    )


def _index_merged_retrievals_for_base_run(
    db: Session,
    *,
    base_result: SearchLegalDocumentsResult,
    merged_items: list[RagSearchResultItem],
) -> list[RagSearchResultItem]:
    """병합된 최종 chunk를 대표 run의 retrieval로 다시 기록합니다."""

    retrievals_by_chunk_id = {
        retrieval.chunk_id: retrieval
        for retrieval in rag_run_repository.list_retrievals_by_run(db, base_result.run_id)
    }
    final_chunk_ids = {item.chunk_id for item in merged_items}
    for chunk_id, retrieval in list(retrievals_by_chunk_id.items()):
        if chunk_id not in final_chunk_ids:
            db.delete(retrieval)
            del retrievals_by_chunk_id[chunk_id]
    for rank, item in enumerate(merged_items, start=1):
        retrieval_type = _retrieval_type_for_item(item)
        retrieval = retrievals_by_chunk_id.get(item.chunk_id)
        if retrieval is None:
            retrieval = RagRetrieval(
                rag_run_id=base_result.run_id,
                chunk_id=item.chunk_id,
                chunk_embedding_id=item.chunk_embedding_id,
                embedding_profile_id=base_result.embedding_profile_id,
                rank=rank,
                score=item.score,
                retrieval_type=retrieval_type,
            )
            rag_run_repository.add_rag_retrieval(db, retrieval)
            retrievals_by_chunk_id[item.chunk_id] = retrieval
        else:
            retrieval.rank = rank
            retrieval.score = item.score
            retrieval.chunk_embedding_id = item.chunk_embedding_id
            retrieval.embedding_profile_id = base_result.embedding_profile_id
            retrieval.retrieval_type = retrieval_type
    db.flush()
    return [
        replace(
            item,
            rank=rank,
            retrieval_id=retrievals_by_chunk_id[item.chunk_id].id,
        )
        for rank, item in enumerate(merged_items, start=1)
    ]


def _review_and_supplement_issue_results(
    db: Session,
    *,
    user_id: int,
    facts: str,
    question: str,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
    embedding_profile: EmbeddingProfile,
    ai_client: AIClient,
    settings: Settings,
    search_mode: str,
    score_threshold: float | None,
    max_chunks_per_document: int | None,
    prompt_version: str,
    timeout_seconds: int,
    document_types: list[str] | None,
) -> list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]]:
    """LLM reviewer가 후보 제거, 누락 보완, 최종 후보 확정을 담당합니다."""

    review = _review_retrieved_evidence(
        ai_client=ai_client,
        settings=settings,
        facts=facts,
        question=question,
        issue_results=issue_results,
    )

    reviewed_results = issue_results
    supplemental_requests: list[_SupplementalRetrievalRequest] = []
    article_refs_for_exact_lookup: list[ExpectedArticleRef] = []
    if review is not None:
        reviewed_results = _apply_reviewed_chunk_ids(
            issue_results,
            keep_chunk_ids=review.keep_chunk_ids,
        )
        supplemental_requests.extend(
            _SupplementalRetrievalRequest(query=query)
            for query in review.supplemental_queries
        )
        article_refs_for_exact_lookup.extend(review.missing_article_refs)
    else:
        # Reviewer가 비활성화된 test/mock 환경에서는 planner hint를 fallback으로만 사용합니다.
        article_refs_for_exact_lookup.extend(_expected_article_refs_from_issues(issue_results))

    reviewed_results = _append_exact_article_ref_results(
        db,
        issue_results=reviewed_results,
        article_refs=article_refs_for_exact_lookup,
        embedding_profile=embedding_profile,
        document_types=document_types,
        issue_key_prefix=(
            "review_exact_article" if review is not None else "fallback_exact_article"
        ),
    )
    supplemental_requests = _dedupe_supplemental_requests(
        [
            *_missing_article_ref_requests(
                reviewed_results,
                article_refs=article_refs_for_exact_lookup,
            ),
            *supplemental_requests,
        ]
    )
    for index, supplemental_request in enumerate(supplemental_requests, start=1):
        supplemental_issue = PlannedLegalIssue(
            issue_key=f"supplemental_{index}",
            title=supplemental_request.query,
            description="LLM evidence review requested supplemental retrieval.",
            internal_rag_query=supplemental_request.query,
            expected_article_refs=(
                [supplemental_request.expected_article_ref]
                if supplemental_request.expected_article_ref is not None
                else []
            ),
        )
        supplemental_result = search_legal_documents(
            db,
            user_id=user_id,
            query=supplemental_request.query,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            search_mode=search_mode,
            top_k=2,
            score_threshold=score_threshold,
            max_chunks_per_document=max_chunks_per_document,
            prompt_version=prompt_version,
            timeout_seconds=timeout_seconds,
            document_types=document_types,
        )
        if supplemental_result.status == "completed":
            reviewed_results.append((supplemental_issue, supplemental_result))

    if review is not None:
        final_review = _review_retrieved_evidence(
            ai_client=ai_client,
            settings=settings,
            facts=facts,
            question=question,
            issue_results=reviewed_results,
        )
        if final_review is not None:
            reviewed_results = _apply_reviewed_chunk_ids(
                reviewed_results,
                keep_chunk_ids=final_review.keep_chunk_ids,
            )
    reviewed_results = _append_coverage_anchor_results(
        db,
        issue_results=reviewed_results,
        embedding_profile=embedding_profile,
        document_types=document_types,
    )
    reviewed_results = _remove_semantic_false_positive_results(reviewed_results)
    return reviewed_results


def _append_exact_article_ref_results(
    db: Session,
    *,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
    article_refs: list[ExpectedArticleRef],
    embedding_profile: EmbeddingProfile,
    document_types: list[str] | None,
    issue_key_prefix: str,
) -> list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]]:
    """Reviewer/fallback이 요청한 조문을 vector score와 무관하게 정확 조회합니다."""

    if not issue_results or not article_refs:
        return issue_results

    all_items = [item for _issue, result in issue_results for item in result.results]
    base_result = issue_results[0][1]
    appended_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]] = []
    seen_refs: set[tuple[str, str]] = set()
    existing_chunk_ids = {item.chunk_id for item in all_items}

    for ref in article_refs:
        ref_key = _expected_article_ref_key(ref)
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)
        if any(_item_matches_expected_article_ref(item, ref) for item in all_items):
            continue
        chunk_embedding = (
            embedding_repository.find_searchable_chunk_embedding_by_article_ref(
                db,
                embedding_profile_id=embedding_profile.id,
                law_title=ref.law_title,
                article_no=ref.article_no,
                document_types=document_types,
            )
        )
        if chunk_embedding is None or chunk_embedding.chunk_id in existing_chunk_ids:
            continue
        if _chunk_embedding_is_invalid(chunk_embedding):
            continue
        query = _query_for_expected_article_ref(ref)
        exact_issue = PlannedLegalIssue(
            issue_key=f"{issue_key_prefix}_{len(appended_results) + 1}",
            title=query,
            description="Reviewer requested exact article lookup.",
            internal_rag_query=query,
            expected_article_refs=[ref],
        )
        exact_item = _exact_article_result_item(
            chunk_embedding=chunk_embedding,
            ref=ref,
        )
        appended_results.append(
            (
                exact_issue,
                replace(
                    base_result,
                    query=query,
                    top_k=1,
                    score_threshold=None,
                    max_chunks_per_document=None,
                    results=[exact_item],
                ),
            )
        )
        all_items.append(exact_item)
        existing_chunk_ids.add(exact_item.chunk_id)

    if not appended_results:
        return issue_results
    return [*issue_results, *appended_results]


def _llm_evidence_review_enabled(*, ai_client: AIClient, settings: Settings) -> bool:
    if settings.ai_agent_provider == "mock":
        return False
    if not settings.source_planner_model_name:
        return False
    return hasattr(ai_client, "generate_text")


def _review_retrieved_evidence(
    *,
    ai_client: AIClient,
    settings: Settings,
    facts: str,
    question: str,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> _EvidenceReviewResult | None:
    model_name = settings.source_planner_model_name
    if not _llm_evidence_review_enabled(ai_client=ai_client, settings=settings):
        return None
    candidates = _review_candidate_payload(issue_results)
    if not candidates:
        return None
    try:
        result = ai_client.generate_text(
            AITextRequest(
                prompt=_build_evidence_review_prompt(
                    facts=facts,
                    question=question,
                    candidates=candidates,
                    expected_article_refs=_expected_article_refs_payload(issue_results),
                ),
                model=model_name,
                temperature=0,
                timeout_seconds=settings.ai_request_timeout_seconds,
                metadata={"purpose": "rag_evidence_review"},
            )
        )
    except ProviderError:
        return None

    parsed = _parse_evidence_review(result.text)
    if parsed is None:
        return None
    return parsed


def _review_candidate_payload(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen_chunk_ids: set[int] = set()
    for issue, result in issue_results:
        for item in result.results:
            if item.chunk_id in seen_chunk_ids:
                continue
            if _is_invalid_retrieval_item(item):
                continue
            seen_chunk_ids.add(item.chunk_id)
            candidates.append(
                {
                    "chunk_id": item.chunk_id,
                    "issue_key": issue.issue_key,
                    "issue_title": issue.title,
                    "query": issue.internal_rag_query,
                    "expected_article_refs": [
                        _expected_article_ref_payload(ref)
                        for ref in issue.expected_article_refs
                    ],
                    "title": item.title,
                    "heading": item.heading,
                    "score": round(item.score, 4),
                    "content": item.content[:1000],
                }
            )
            if len(candidates) >= 30:
                return candidates
    return candidates


def _build_evidence_review_prompt(
    *,
    facts: str,
    question: str,
    candidates: list[dict[str, object]],
    expected_article_refs: list[dict[str, object]],
) -> str:
    schema = {
        "keep_chunk_ids": [1, 2],
        "discard_chunk_ids": [3],
        "supplemental_queries": ["형법 사체유기 변사체 검시 방해"],
        "missing_article_refs": [
            {
                "law_title": "형법",
                "article_no": "제161조",
                "article_title": "시체 등의 유기 등",
                "reason": "facts mention burial of a corpse",
            }
        ],
    }
    return (
        "You review Korean legal RAG evidence candidates.\n"
        "Return only JSON. Do not include markdown.\n"
        "First identify the essential legal issues raised by the facts/question, "
        "then keep candidates that cover any essential issue.\n"
        "Do not discard a candidate only because its vector score is low. Keep "
        "low-score chunks when they are necessary for legal issue coverage.\n"
        "Exclude only chunks that are unrelated, misleading, duplicative, or not "
        "useful for any essential issue.\n"
        "Keep an article only when its heading/content directly governs a factual "
        "issue. Discard adjacent chapter headings, penalty add-ons, age/disability "
        "rules, execution-stage rules, or procedural victim-notice rules when they "
        "do not directly answer the facts/question.\n"
        "Planner-provided expected_article_refs are unverified hints, not authority. "
        "Do not keep or exact-lookup an article only because the planner suggested it.\n"
        "If a candidate confuses different legal objects, discard it. For example, "
        "hiding a corpse is not the same issue as hiding an offender unless facts "
        "mention a third person hiding or helping the offender.\n"
        "When facts describe the actor hiding a corpse/body, discard 범인은닉, "
        "범인은닉과친족간의특례, or offender-hiding articles unless the facts "
        "separately mention another person hiding the offender.\n"
        "Coverage checklist for criminal facts: accidental death requires both the "
        "specific death offense and the negligence principle when available; burial "
        "or concealment of a body requires corpse-disposal and inspection-obstruction "
        "coverage when available; self-reporting to police requires self-surrender "
        "or confession-effect coverage when available; a missing body or uncertain "
        "burial location requires investigation/inspection-disposition coverage when "
        "available.\n"
        "For accidental or unintentional death facts, if candidates include both a "
        "negligent-death article and a general negligence-principle article, keep "
        "both. They are complementary, not duplicative.\n"
        "For body burial or concealment facts, if candidates include both a corpse "
        "disposal article and a suspicious-corpse examination obstruction article, "
        "keep both. They are complementary, not duplicative.\n"
        "For self-reporting to police, discard articles whose text limits confession "
        "or surrender effects to a specific preceding offense unless the facts concern "
        "that preceding offense. Prefer the general self-surrender/confession article "
        "when it is available.\n"
        "For body burial before official examination, keep an inspection-obstruction "
        "article when its heading/content directly addresses concealment, alteration, "
        "or obstruction of examination of a suspicious corpse.\n"
        "If an essential issue is missing, add at most 2 concise supplemental "
        "Korean retrieval queries. Do not add queries when current evidence is enough.\n"
        "If you can identify a necessary statute article that is missing from kept "
        "chunks, report it in missing_article_refs with law_title and article_no. "
        "Use this only for articles you judge necessary from the facts/question.\n"
        f"Schema example:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"facts:\n{facts.strip()}\n\n"
        f"question:\n{question.strip()}\n\n"
        f"expected_article_refs:\n{json.dumps(expected_article_refs, ensure_ascii=False)}\n\n"
        f"candidates:\n{json.dumps(candidates, ensure_ascii=False)}\n"
    )


def _parse_evidence_review(text: str) -> _EvidenceReviewResult | None:
    try:
        payload = json.loads(_extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_keep_chunk_ids = payload.get("keep_chunk_ids")
    if not isinstance(raw_keep_chunk_ids, list):
        return None
    keep_chunk_ids = [
        value
        for value in raw_keep_chunk_ids
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    supplemental_queries = [
        value.strip()
        for value in payload.get("supplemental_queries", [])
        if isinstance(value, str) and value.strip()
    ][:2]
    missing_article_refs = _article_refs_from_review_payload(
        payload.get("missing_article_refs")
        or payload.get("missing_expected_article_refs")
        or []
    )
    return _EvidenceReviewResult(
        keep_chunk_ids=keep_chunk_ids,
        supplemental_queries=supplemental_queries,
        missing_article_refs=missing_article_refs,
    )


def _article_refs_from_review_payload(raw_refs: object) -> list[ExpectedArticleRef]:
    if not isinstance(raw_refs, list):
        return []
    refs = [
        ref
        for item in raw_refs
        if (ref := _article_ref_from_review_payload(item)) is not None
    ]
    deduped: list[ExpectedArticleRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = _expected_article_ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
        if len(deduped) >= 8:
            break
    return deduped


def _article_ref_from_review_payload(value: object) -> ExpectedArticleRef | None:
    if not isinstance(value, dict):
        return None
    law_title = _string_value(value.get("law_title")) or _string_value(
        value.get("title")
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
        article_no=re.sub(r"\s+", "", article_no),
        article_title=_string_value(value.get("article_title")),
        reason=_string_value(value.get("reason")),
    )


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _exact_article_result_item(
    *,
    chunk_embedding,
    ref: ExpectedArticleRef,
) -> RagSearchResultItem:
    chunk = chunk_embedding.chunk
    document = chunk.document
    metadata = {
        **(chunk.metadata_json or {}),
        "document_type": document.document_type,
        "canonical_id": document.canonical_id,
        "version_label": document.version_label,
        "retrieval_type": "exact_article",
        "expected_article_ref": _expected_article_ref_payload(ref),
    }
    return RagSearchResultItem(
        retrieval_id=None,
        chunk_embedding_id=chunk_embedding.id,
        chunk_id=chunk.id,
        document_id=document.id,
        rank=1,
        score=1.0,
        title=document.title,
        source_url=document.source.source_url if document.source else None,
        heading=chunk.heading,
        content=chunk.content,
        metadata_json=metadata,
    )


def _keyword_hint_result_item(
    *,
    chunk_embedding,
    keyword_score: float,
) -> RagSearchResultItem:
    chunk = chunk_embedding.chunk
    document = chunk.document
    metadata = {
        **(chunk.metadata_json or {}),
        "document_type": document.document_type,
        "canonical_id": document.canonical_id,
        "version_label": document.version_label,
        "retrieval_type": "keyword_heading",
    }
    return RagSearchResultItem(
        retrieval_id=None,
        chunk_embedding_id=chunk_embedding.id,
        chunk_id=chunk.id,
        document_id=document.id,
        rank=1,
        score=min(0.99, 0.55 + keyword_score / 20),
        title=document.title,
        source_url=document.source.source_url if document.source else None,
        heading=chunk.heading,
        content=chunk.content,
        metadata_json=metadata,
    )


def _coverage_anchor_result_item(*, chunk_embedding) -> RagSearchResultItem:
    chunk = chunk_embedding.chunk
    document = chunk.document
    metadata = {
        **(chunk.metadata_json or {}),
        "document_type": document.document_type,
        "canonical_id": document.canonical_id,
        "version_label": document.version_label,
        "retrieval_type": "coverage_anchor",
    }
    return RagSearchResultItem(
        retrieval_id=None,
        chunk_embedding_id=chunk_embedding.id,
        chunk_id=chunk.id,
        document_id=document.id,
        rank=1,
        score=0.98,
        title=document.title,
        source_url=document.source.source_url if document.source else None,
        heading=chunk.heading,
        content=chunk.content,
        metadata_json=metadata,
    )


def _coverage_anchor_matches(
    chunk_embeddings,
    *,
    query: str,
):
    normalized_query = _normalize_for_keyword_match(query)
    if not normalized_query:
        return []

    matches = []
    for chunk_embedding in chunk_embeddings:
        chunk = chunk_embedding.chunk
        document = chunk.document
        title = _normalize_for_keyword_match(document.title)
        heading = _normalize_for_keyword_match(chunk.heading or "")
        heading_title = _normalized_heading_title(chunk.heading or "")
        content_prefix = _normalize_for_keyword_match(chunk.content[:500])
        if _matches_coverage_anchor(
            normalized_query=normalized_query,
            title=title,
            heading=heading,
            heading_title=heading_title,
            content_prefix=content_prefix,
        ):
            matches.append(chunk_embedding)
    matches.sort(key=lambda item: item.id)
    return matches


def _matches_coverage_anchor(
    *,
    normalized_query: str,
    title: str,
    heading: str,
    heading_title: str,
    content_prefix: str,
) -> bool:
    if "형법" in title:
        if (
            "과실" in normalized_query
            and ("과실치사" in normalized_query or "사망" in normalized_query)
            and heading_title == "과실"
        ):
            return True
        if (
            "자수" in normalized_query
            and heading_title == "자수자복"
            and "전조" not in content_prefix
        ):
            return True
        if (
            ("사체" in normalized_query or "시체" in normalized_query)
            and ("유기" in normalized_query or "매장" in normalized_query)
            and heading_title == "시체등의유기등"
        ):
            return True
        if (
            "검시" in normalized_query
            and "방해" in normalized_query
            and heading_title == "변사체검시방해"
        ):
            return True
    if "형사소송법" in title:
        if (
            ("시체" in normalized_query or "사체" in normalized_query)
            and ("발굴" in normalized_query or "검증" in normalized_query)
            and heading_title == "검증과필요한처분"
        ):
            return True
    return False


def _is_semantic_false_positive(
    item: RagSearchResultItem,
    *,
    issue: PlannedLegalIssue,
) -> bool:
    normalized_query = _normalize_for_keyword_match(issue.internal_rag_query)
    title = _normalize_for_keyword_match(item.title)
    heading = _normalize_for_keyword_match(item.heading or "")
    content_prefix = _normalize_for_keyword_match(item.content[:500])
    if "형법" in title and "범인은닉" in heading and "범인은닉" not in normalized_query:
        return True
    if (
        "형법" in title
        and "자수" in heading
        and "전조" in content_prefix
        and not any(token in normalized_query for token in ("위증", "무고", "모해"))
    ):
        return True
    return False


def _keyword_heading_matches(
    chunk_embeddings,
    *,
    query: str,
    limit: int,
):
    tokens = _keyword_hint_tokens(query)
    if not tokens or limit <= 0:
        return []

    scored = []
    for chunk_embedding in chunk_embeddings:
        chunk = chunk_embedding.chunk
        document = chunk.document
        title = _normalize_for_keyword_match(document.title)
        heading = _normalize_for_keyword_match(chunk.heading or "")
        content_prefix = _normalize_for_keyword_match(chunk.content[:500])
        score = 0
        for token in tokens:
            if token in heading:
                score += 4
            elif token in content_prefix:
                score += 2
            elif token in title:
                score += 1
        if score >= 4:
            scored.append((chunk_embedding, float(score)))

    scored.sort(key=lambda item: (-item[1], item[0].id))
    return scored[:limit]


def _keyword_hint_tokens(query: str) -> list[str]:
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", " ", query)
    stopwords = {
        "관련",
        "검토",
        "가능성",
        "결과",
        "경우",
        "사람",
        "사망",
        "쟁점",
        "조문",
        "형법",
        "형사소송법",
    }
    tokens: list[str] = []
    seen: set[str] = set()
    for token in normalized.split():
        token = token.strip().lower()
        if len(token) < 2 or token in stopwords or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens[:12]


def _normalize_for_keyword_match(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _normalized_heading_title(heading: str) -> str:
    match = re.search(r"제\s*\d+\s*조(?:의\s*\d+)?\s*\(([^)]*)\)", heading)
    if match is not None:
        value = _normalize_for_keyword_match(match.group(1))
    else:
        value = _normalize_for_keyword_match(heading)
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value)


def _retrieval_type_for_item(item: RagSearchResultItem) -> str:
    value = item.metadata_json.get("retrieval_type")
    if isinstance(value, str) and value.strip():
        return value.strip()[:30]
    return "vector"


def _expected_article_refs_payload(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for issue, _result in issue_results:
        for ref in issue.expected_article_refs:
            key = _expected_article_ref_key(ref)
            if key in seen:
                continue
            seen.add(key)
            payload = _expected_article_ref_payload(ref)
            payload["issue_key"] = issue.issue_key
            payload["issue_title"] = issue.title
            if issue.domain:
                payload["domain"] = issue.domain
            if issue.facts_slice:
                payload["facts_slice"] = issue.facts_slice
            refs.append(payload)
    return refs


def _expected_article_ref_payload(ref: ExpectedArticleRef) -> dict[str, object]:
    payload: dict[str, object] = {
        "law_title": ref.law_title,
        "article_no": ref.article_no,
    }
    if ref.article_title:
        payload["article_title"] = ref.article_title
    if ref.reason:
        payload["reason"] = ref.reason
    return payload


def _expected_article_refs_from_issues(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> list[ExpectedArticleRef]:
    refs: list[ExpectedArticleRef] = []
    seen: set[tuple[str, str]] = set()
    for issue, _result in issue_results:
        for ref in issue.expected_article_refs:
            key = _expected_article_ref_key(ref)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _missing_article_ref_requests(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
    *,
    article_refs: list[ExpectedArticleRef],
) -> list[_SupplementalRetrievalRequest]:
    requests: list[_SupplementalRetrievalRequest] = []
    seen_refs: set[tuple[str, str]] = set()
    all_items = [item for _issue, result in issue_results for item in result.results]
    for ref in article_refs:
        key = _expected_article_ref_key(ref)
        if key in seen_refs:
            continue
        seen_refs.add(key)
        if any(_item_matches_expected_article_ref(item, ref) for item in all_items):
            continue
        requests.append(
            _SupplementalRetrievalRequest(
                query=_query_for_expected_article_ref(ref),
                expected_article_ref=ref,
            )
        )
    return requests


def _item_matches_expected_article_ref(
    item: RagSearchResultItem,
    ref: ExpectedArticleRef,
) -> bool:
    if _is_invalid_retrieval_item(item):
        return False

    title = _normalize_for_article_match(item.title)
    law_title = _normalize_for_article_match(ref.law_title)
    if law_title and law_title not in title:
        return False

    article_no = _normalize_for_article_match(ref.article_no)
    metadata_article_no = _normalize_for_article_match(
        str(item.metadata_json.get("article_no") or "")
    )
    heading = _normalize_for_article_match(item.heading or "")
    content_prefix = _normalize_for_article_match(item.content[:200])
    return (
        metadata_article_no == article_no
        or article_no in heading
        or article_no in content_prefix
    )


def _query_for_expected_article_ref(ref: ExpectedArticleRef) -> str:
    values = [ref.law_title, ref.article_no, ref.article_title or "", ref.reason or ""]
    return " ".join(value.strip() for value in values if value.strip())


def _chunk_embedding_is_invalid(chunk_embedding) -> bool:
    chunk = chunk_embedding.chunk
    return _is_invalid_chunk_content(heading=chunk.heading, content=chunk.content)


def _is_invalid_retrieval_item(item: RagSearchResultItem) -> bool:
    return _is_invalid_chunk_content(heading=item.heading, content=item.content)


def _is_invalid_chunk_content(*, heading: str | None, content: str) -> bool:
    return is_title_only_article_chunk(
        heading=heading,
        content=content,
    ) or has_article_boundary_contamination(
        heading=heading,
        content=content,
    )


def _dedupe_supplemental_requests(
    requests: list[_SupplementalRetrievalRequest],
) -> list[_SupplementalRetrievalRequest]:
    deduped: list[_SupplementalRetrievalRequest] = []
    seen_queries: set[str] = set()
    for request in requests:
        key = _normalize_for_article_match(request.query)
        if not key or key in seen_queries:
            continue
        seen_queries.add(key)
        deduped.append(request)
        if len(deduped) >= 8:
            break
    return deduped


def _expected_article_ref_key(ref: ExpectedArticleRef) -> tuple[str, str]:
    return (
        _normalize_for_article_match(ref.law_title),
        _normalize_for_article_match(ref.article_no),
    )


def _normalize_for_article_match(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


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


def _apply_reviewed_chunk_ids(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
    *,
    keep_chunk_ids: list[int],
) -> list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]]:
    keep_set = set(keep_chunk_ids)
    return [
        (
            issue,
            replace(
                result,
                results=[item for item in result.results if item.chunk_id in keep_set],
            ),
        )
        for issue, result in issue_results
    ]


def _tag_item_with_issue(
    item: RagSearchResultItem,
    issue: PlannedLegalIssue,
) -> RagSearchResultItem:
    metadata = dict(item.metadata_json)
    issue_payload = {
        "issue_key": issue.issue_key,
        "issue_title": issue.title,
        "issue_query": issue.internal_rag_query,
    }
    if issue.domain:
        issue_payload["domain"] = issue.domain
    if issue.facts_slice:
        issue_payload["facts_slice"] = issue.facts_slice
    metadata["planned_issue_key"] = issue.issue_key
    metadata["planned_issue_title"] = issue.title
    metadata["planned_issue_query"] = issue.internal_rag_query
    if issue.domain:
        metadata["planned_issue_domain"] = issue.domain
        metadata["domain_tags"] = _merge_metadata_string_values(
            metadata.get("domain_tags"),
            issue.domain,
        )
    if issue.facts_slice:
        metadata["planned_issue_facts_slice"] = issue.facts_slice
    metadata["used_by_tracks"] = _merge_metadata_string_values(
        metadata.get("used_by_tracks"),
        issue.issue_key,
    )
    metadata["planned_issue_queries"] = [issue_payload]
    return replace(item, metadata_json=metadata)


def _merge_duplicate_item(
    existing_item: RagSearchResultItem,
    new_item: RagSearchResultItem,
) -> RagSearchResultItem:
    metadata = dict(existing_item.metadata_json)
    planned_queries = list(metadata.get("planned_issue_queries") or [])
    new_queries = list(new_item.metadata_json.get("planned_issue_queries") or [])
    seen_issue_keys = {
        query.get("issue_key")
        for query in planned_queries
        if isinstance(query, dict)
    }
    for query in new_queries:
        if not isinstance(query, dict):
            continue
        if query.get("issue_key") in seen_issue_keys:
            continue
        planned_queries.append(query)
        seen_issue_keys.add(query.get("issue_key"))
    metadata["planned_issue_queries"] = planned_queries
    metadata["domain_tags"] = _merge_metadata_string_values(
        metadata.get("domain_tags"),
        new_item.metadata_json.get("domain_tags"),
    )
    metadata["used_by_tracks"] = _merge_metadata_string_values(
        metadata.get("used_by_tracks"),
        new_item.metadata_json.get("used_by_tracks"),
    )
    return replace(
        existing_item,
        score=max(existing_item.score, new_item.score),
        metadata_json=metadata,
    )


def _merge_metadata_string_values(*values: object) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw_items: list[object]
        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = [value]
        for raw_item in raw_items:
            if not isinstance(raw_item, str):
                continue
            item = raw_item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _prioritize_expected_article_items(
    items: list[RagSearchResultItem],
) -> list[RagSearchResultItem]:
    """Reviewer가 요청한 exact lookup 근거를 최종 검색 결과 상단에 배치합니다."""

    return [
        item
        for _index, item in sorted(
            enumerate(items),
            key=lambda indexed_item: (
                _expected_article_item_priority(indexed_item[1]),
                indexed_item[0],
            ),
        )
    ]


def _expected_article_item_priority(item: RagSearchResultItem) -> int:
    if _retrieval_type_for_item(item) == "exact_article":
        return 0
    return 1


def _issues_or_default(
    plan: LegalSourcePlan,
    original_query: str,
) -> list[PlannedLegalIssue]:
    if plan.issues:
        return plan.issues
    return [
        PlannedLegalIssue(
            issue_key="issue_1",
            title=original_query[:120],
            description=None,
            internal_rag_query=original_query,
            official_source_query=None,
            candidates=plan.candidates,
        )
    ]


def _statute_candidates(plan: LegalSourcePlan) -> list[LegalSourceCandidate]:
    candidates = [
        candidate
        for candidate in plan.candidates
        if candidate.document_type == "statute"
    ]
    seen: set[str] = set()
    unique_candidates: list[LegalSourceCandidate] = []
    for candidate in candidates:
        key = candidate.query.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates


def _preferred_titles_for_candidate(candidate: LegalSourceCandidate) -> list[str]:
    titles: list[str] = []
    for value in (candidate.title, candidate.query):
        if value.strip() and value not in titles:
            titles.append(value)
    return titles


def _official_source_sync_query(candidate: LegalSourceCandidate) -> str:
    return candidate.title.strip() or candidate.query.strip()


def _official_source_search_limit(settings: Settings) -> int:
    return min(max(settings.ai_source_planner_max_candidates, 1), 20)


def _combined_query(*, facts: str, question: str) -> str:
    values = [value.strip() for value in (facts, question) if value.strip()]
    return "\n".join(values)
