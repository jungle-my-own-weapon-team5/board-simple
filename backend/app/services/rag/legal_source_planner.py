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
    "개인정보 보호법",
    "민사소송법",
    "민사집행법",
    "형사소송법",
)


@dataclass(frozen=True)
class LegalSourceCandidate:
    """공식 법령 API 조회에 사용할 검증된 후보입니다."""

    document_type: str
    title: str
    query: str
    reason: str | None = None


@dataclass(frozen=True)
class LegalSourcePlan:
    """LLM 후보 추출 결과와 원문 응답을 함께 보관합니다."""

    candidates: list[LegalSourceCandidate] = field(default_factory=list)
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
    if not model_name:
        return LegalSourcePlan(
            candidates=_fallback_candidates(facts, question, limit=candidate_limit)
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
        return LegalSourcePlan(
            candidates=_fallback_candidates(facts, question, limit=candidate_limit)
        )
    candidates = _parse_candidates(result.text, limit=candidate_limit)
    if not candidates:
        candidates = _fallback_candidates(facts, question, limit=candidate_limit)
    return LegalSourcePlan(candidates=candidates, raw_text=result.text)


def _build_planner_prompt(
    *,
    facts: str,
    question: str,
    search_mode: str,
    max_candidates: int,
) -> str:
    return (
        "You select Korean official legal source search candidates for RAG.\n"
        "Return only a JSON object. Do not include markdown.\n"
        "The candidates are not legal conclusions and must not be cited directly.\n"
        "Each candidate must target an official statute search.\n"
        f"Return at most {max_candidates} candidates.\n"
        "Schema:\n"
        "{\"candidates\":[{\"document_type\":\"statute\","
        "\"title\":\"주택임대차보호법\",\"query\":\"주택임대차보호법\","
        "\"reason\":\"임대차 보증금 반환 쟁점\"}]}\n"
        "Prefer exact statute titles when possible. If unsure, include a concise "
        "Korean search query.\n\n"
        f"search_mode: {search_mode}\n"
        f"facts:\n{facts.strip()}\n\n"
        f"question:\n{question.strip()}\n"
    )


def _parse_candidates(text: str, *, limit: int) -> list[LegalSourceCandidate]:
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


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()
