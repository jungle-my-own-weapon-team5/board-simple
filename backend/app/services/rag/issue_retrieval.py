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


TRUSTED_EXPECTED_ARTICLE_ISSUE_KEYS = {
    "criminal_negligent_death",
    "criminal_corpse_concealment",
    "criminal_self_surrender",
    "criminal_procedure_body_search",
}


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
    trusted_expected_ref_keys = _trusted_expected_article_ref_keys(issue_results)
    for issue, result in issue_results:
        for item in result.results:
            tagged_item = _tag_item_with_issue(item, issue)
            if _should_skip_secondary_article_item(
                tagged_item,
                original_query=original_query,
                trusted_expected_ref_keys=trusted_expected_ref_keys,
            ):
                continue
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
    """LLM으로 검색 후보를 1회 검토하고 부족한 쟁점 query를 소량 보강합니다."""

    review = _review_retrieved_evidence(
        ai_client=ai_client,
        settings=settings,
        facts=facts,
        question=question,
        issue_results=issue_results,
    )

    reviewed_results = issue_results
    supplemental_requests: list[_SupplementalRetrievalRequest] = []
    if review is not None:
        reviewed_results = _apply_reviewed_chunk_ids(
            issue_results,
            keep_chunk_ids=review["keep_chunk_ids"],
        )
        supplemental_requests.extend(
            _SupplementalRetrievalRequest(query=query)
            for query in review["supplemental_queries"]
        )

    reviewed_results = _append_exact_expected_article_results(
        db,
        issue_results=reviewed_results,
        embedding_profile=embedding_profile,
        document_types=document_types,
    )
    supplemental_requests = _dedupe_supplemental_requests(
        [
            *_missing_expected_article_ref_requests(reviewed_results),
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
    return reviewed_results


def _append_exact_expected_article_results(
    db: Session,
    *,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
    embedding_profile: EmbeddingProfile,
    document_types: list[str] | None,
) -> list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]]:
    """필수 조문 후보를 vector score와 무관하게 정확 조회해 결과에 추가합니다."""

    if not issue_results:
        return issue_results

    all_items = [item for _issue, result in issue_results for item in result.results]
    base_result = issue_results[0][1]
    appended_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]] = []
    seen_refs: set[tuple[str, str]] = set()
    existing_chunk_ids = {item.chunk_id for item in all_items}

    for issue, _result in issue_results:
        for ref in _trusted_expected_article_refs(issue):
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
            query = _query_for_expected_article_ref(ref)
            exact_issue = PlannedLegalIssue(
                issue_key=f"exact_article_{len(appended_results) + 1}",
                title=query,
                description="필수 조문 후보를 조문번호로 정확 조회했습니다.",
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


def _review_retrieved_evidence(
    *,
    ai_client: AIClient,
    settings: Settings,
    facts: str,
    question: str,
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> dict[str, list[int] | list[str]] | None:
    model_name = settings.source_planner_model_name
    if settings.ai_agent_provider == "mock":
        return None
    if not model_name or not hasattr(ai_client, "generate_text"):
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
            seen_chunk_ids.add(item.chunk_id)
            candidates.append(
                {
                    "chunk_id": item.chunk_id,
                    "issue_key": issue.issue_key,
                    "issue_title": issue.title,
                    "query": issue.internal_rag_query,
                    "expected_article_refs": [
                        _expected_article_ref_payload(ref)
                        for ref in _trusted_expected_article_refs(issue)
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
        "supplemental_queries": ["형법 사체유기 조문"],
        "missing_expected_article_refs": [
            {"law_title": "형법", "article_no": "제161조"}
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
        "If an essential issue is missing, add at most 2 concise supplemental "
        "Korean retrieval queries. Do not add queries when current evidence is enough.\n"
        "Also check expected_article_refs. If any expected article is not covered by "
        "kept chunks, report it in missing_expected_article_refs and add a supplemental "
        "query containing the statute title and article number.\n"
        f"Schema example:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"facts:\n{facts.strip()}\n\n"
        f"question:\n{question.strip()}\n\n"
        f"expected_article_refs:\n{json.dumps(expected_article_refs, ensure_ascii=False)}\n\n"
        f"candidates:\n{json.dumps(candidates, ensure_ascii=False)}\n"
    )


def _parse_evidence_review(text: str) -> dict[str, list[int] | list[str]] | None:
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
    return {
        "keep_chunk_ids": keep_chunk_ids,
        "supplemental_queries": supplemental_queries,
    }


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
        for ref in _trusted_expected_article_refs(issue):
            key = _expected_article_ref_key(ref)
            if key in seen:
                continue
            seen.add(key)
            payload = _expected_article_ref_payload(ref)
            payload["issue_key"] = issue.issue_key
            payload["issue_title"] = issue.title
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


def _missing_expected_article_ref_requests(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> list[_SupplementalRetrievalRequest]:
    requests: list[_SupplementalRetrievalRequest] = []
    seen_refs: set[tuple[str, str]] = set()
    all_items = [item for _issue, result in issue_results for item in result.results]
    for issue, _result in issue_results:
        for ref in _trusted_expected_article_refs(issue):
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


def _trusted_expected_article_refs(issue: PlannedLegalIssue) -> list[ExpectedArticleRef]:
    if issue.issue_key in TRUSTED_EXPECTED_ARTICLE_ISSUE_KEYS:
        return issue.expected_article_refs
    if any(candidate.reason == "required_article_ref" for candidate in issue.candidates):
        return issue.expected_article_refs
    return []


def _trusted_expected_article_ref_keys(
    issue_results: list[tuple[PlannedLegalIssue, SearchLegalDocumentsResult]],
) -> set[tuple[str, str]]:
    return {
        _expected_article_ref_key(ref)
        for issue, _result in issue_results
        for ref in _trusted_expected_article_refs(issue)
    }


def _should_skip_secondary_article_item(
    item: RagSearchResultItem,
    *,
    original_query: str,
    trusted_expected_ref_keys: set[tuple[str, str]],
) -> bool:
    self_surrender_key = (
        _normalize_for_article_match("형법"),
        _normalize_for_article_match("제52조"),
    )
    sentencing_condition_key = (
        _normalize_for_article_match("형법"),
        _normalize_for_article_match("제51조"),
    )
    if self_surrender_key not in trusted_expected_ref_keys:
        return False
    if sentencing_condition_key in trusted_expected_ref_keys:
        return False
    if _item_matches_expected_article_ref(
        item,
        ExpectedArticleRef(law_title="형법", article_no="제51조"),
    ):
        return True
    if _item_matches_expected_article_ref(
        item,
        ExpectedArticleRef(law_title="형법", article_no="제151조"),
    ):
        return not _has_offender_hiding_fact(original_query)
    return False


def _has_offender_hiding_fact(text: str) -> bool:
    normalized = _normalize_for_article_match(text)
    return any(
        keyword in normalized
        for keyword in (
            "범인은닉",
            "범인도피",
            "범인을숨",
            "범인을도피",
            "도피시키",
            "숨겨주",
            "숨겨준",
        )
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
    metadata["planned_issue_key"] = issue.issue_key
    metadata["planned_issue_title"] = issue.title
    metadata["planned_issue_query"] = issue.internal_rag_query
    metadata["planned_issue_queries"] = [issue_payload]
    matched_expected_refs = [
        _expected_article_ref_payload(ref)
        for ref in _trusted_expected_article_refs(issue)
        if _item_matches_expected_article_ref(item, ref)
    ]
    if matched_expected_refs:
        metadata["matched_expected_article_refs"] = matched_expected_refs
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
    metadata["matched_expected_article_refs"] = _merge_expected_article_ref_payloads(
        metadata.get("matched_expected_article_refs"),
        new_item.metadata_json.get("matched_expected_article_refs"),
    )
    return replace(
        existing_item,
        score=max(existing_item.score, new_item.score),
        metadata_json=metadata,
    )


def _prioritize_expected_article_items(
    items: list[RagSearchResultItem],
) -> list[RagSearchResultItem]:
    """필수 조문과 직접 매칭되는 근거를 최종 검색 결과 상단에 배치합니다."""

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
    if item.metadata_json.get("matched_expected_article_refs"):
        return 1
    return 2


def _merge_expected_article_ref_payloads(
    existing_value: object,
    new_value: object,
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for value in (existing_value, new_value):
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            key = (
                _normalize_for_article_match(str(item.get("law_title") or "")),
                _normalize_for_article_match(str(item.get("article_no") or "")),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


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
