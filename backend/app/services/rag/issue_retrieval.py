"""LLM 쟁점 계획을 먼저 수행한 뒤 쟁점별 RAG 검색을 조율합니다."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.embedding import EmbeddingProfile
from app.services.ai.client import AIClient
from app.services.rag.legal_open_api import LawOpenApiClient, LawOpenApiError
from app.services.rag.legal_open_api_sync import sync_and_embed_law_open_api_statute
from app.services.rag.legal_source_planner import (
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

    return _merge_issue_results(
        original_query=original_query,
        issue_results=issue_results,
    )


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
                query=candidate.query,
                embedding_profile=embedding_profile,
                ai_client=ai_client,
                search_limit=_official_source_search_limit(settings),
                preferred_titles=_preferred_titles_for_candidate(candidate),
                timeout_seconds=timeout_seconds,
            )
        except LawOpenApiError:
            continue


def _merge_issue_results(
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
    return replace(
        base_result,
        query=original_query,
        results=merged_items,
    )


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
    metadata["planned_issue_key"] = issue.issue_key
    metadata["planned_issue_title"] = issue.title
    metadata["planned_issue_query"] = issue.internal_rag_query
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
    return replace(
        existing_item,
        score=max(existing_item.score, new_item.score),
        metadata_json=metadata,
    )


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


def _official_source_search_limit(settings: Settings) -> int:
    return min(max(settings.ai_source_planner_max_candidates, 1), 20)


def _combined_query(*, facts: str, question: str) -> str:
    values = [value.strip() for value in (facts, question) if value.strip()]
    return "\n".join(values)
