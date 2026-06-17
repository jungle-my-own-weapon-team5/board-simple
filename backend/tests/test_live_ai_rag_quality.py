from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.main import app


pytestmark = pytest.mark.live

FRONTEND_ORIGIN = "http://localhost:3000"
LIVE_FACTS = (
    "A는 실수로 모르는 사람 B를 죽였습니다. A는 두려움에 술을 마시고 "
    "인사불성이 된 상태로 사건 현장으로 돌아가 B를 근처에 있는 비닐백에 "
    "담은 뒤 인근 야산에 가서 매장하였습니다.\n"
    "죄책감에 시달린 A는 1주일 후에 경찰서에 가서 자수를 하였습니다.\n"
    "경찰은 A가 지목한 장소로 갔으나, A가 시체를 매장한 장소를 정확히 "
    "떠올리지 못하였고, 결국 시체를 찾지 못해 수사가 난항에 빠졌습니다.\n"
    "근방에서 실종자 수색도 함께 진행하였으나 실종된 것으로 식별된 사람이 "
    "없어 B가 누구인지도 알지 못하는 상태입니다."
)
LIVE_QUESTION = "검토해야 할 쟁점과 답변 초안 방향을 알려주세요."
LIVE_QUERY = f"- 사실관계: {LIVE_FACTS}\n- 질문: {LIVE_QUESTION}"
REQUIRED_SEARCH_REFS = (
    ("형법", "제14조"),
    ("형법", "제52조"),
    ("형법", "제161조"),
    ("형법", "제267조"),
)
IMPORTANT_OPTIONAL_REFS = (
    ("형법", "제163조"),
    ("형사소송법", "제140조"),
)
FORBIDDEN_PHRASES = (
    "군수용자",
    "군에서의 형의 집행",
    "군교정시설",
)
CHATBOT_TAIL_PHRASES = (
    "원하시면",
    "더 다듬어 드릴게요",
    "다시 정리해드릴게요",
)


@dataclass(frozen=True)
class LiveApiContext:
    client: TestClient
    session_factory: sessionmaker[Session]


def test_live_criminal_story_rag_outputs_quality() -> None:
    """실제 OpenAI/국가법령정보 API로 검색, 쟁점 정리, 답변 초안을 검증합니다.

    이 테스트는 비용과 외부 API 호출이 발생하므로 기본 pytest에서는 실행하지 않습니다.
    """

    if os.getenv("RUN_LIVE_AI_RAG_TEST") != "1":
        pytest.skip("set RUN_LIVE_AI_RAG_TEST=1 to run live external API test")

    settings = _live_settings_or_skip()
    with _client_context(settings) as context:
        register_and_login(context.client, email="live-ai-rag@example.com")

        search_body = _post_json(
            context.client,
            "/api/rag/search",
            {
                "query": LIVE_QUERY,
                "search_mode": "issue_spotting",
                "top_k": 3,
                "filters": {"document_type": "statute"},
            },
        )
        issues_body = _post_json(
            context.client,
            "/api/ai/dispute-issues",
            {
                "facts": LIVE_FACTS,
                "question": LIVE_QUESTION,
                "search_mode": "issue_spotting",
                "top_k": 3,
            },
        )
        draft_body = _post_json(
            context.client,
            "/api/ai/answer-drafts",
            {
                "facts": LIVE_FACTS,
                "question": LIVE_QUESTION,
                "search_mode": "issue_spotting",
                "top_k": 3,
                "tone": "formal",
            },
        )

    quality = _evaluate_quality(search_body, issues_body, draft_body)
    _print_live_report(search_body, issues_body, draft_body, quality)

    assert search_body["items"], "live RAG search returned no items"
    assert not quality["forbidden_phrase_hits"], quality["forbidden_phrase_hits"]
    assert not quality["chatbot_tail_hits"], quality["chatbot_tail_hits"]
    assert not quality["article_mismatch_hits"], quality["article_mismatch_hits"]
    assert not quality["irrelevant_article_hits"], quality["irrelevant_article_hits"]
    assert not quality["missing_required_search_refs"], quality[
        "missing_required_search_refs"
    ]
    assert quality["issue_coverage_passed"], quality["issue_coverage"]
    assert quality["draft_coverage_passed"], quality["draft_coverage"]


def _live_settings_or_skip() -> Settings:
    base = Settings(app_env="test", ai_rag_enabled=False)
    missing = []
    if not base.openai_api_key.strip():
        missing.append("OPENAI_API_KEY")
    if not base.law_open_api_oc.strip():
        missing.append("LAW_OPEN_API_OC")
    if not base.ai_agent_model.strip():
        missing.append("AI_AGENT_MODEL")
    if not base.ai_embedding_model.strip():
        missing.append("AI_EMBEDDING_MODEL")
    if base.ai_embedding_dimensions is None or base.ai_embedding_dimensions <= 0:
        missing.append("AI_EMBEDDING_DIMENSIONS")
    if missing:
        pytest.skip("live AI/RAG test requires: " + ", ".join(missing))

    return Settings(
        app_env="test",
        ai_rag_enabled=True,
        ai_agent_provider="openai",
        ai_embedding_provider="openai",
        ai_agent_model=base.ai_agent_model,
        ai_source_planner_model=base.source_planner_model_name,
        ai_source_planner_max_candidates=max(base.ai_source_planner_max_candidates, 5),
        ai_embedding_model=base.ai_embedding_model,
        ai_embedding_dimensions=base.ai_embedding_dimensions,
        ai_request_timeout_seconds=max(base.ai_request_timeout_seconds, 90),
        ai_agent_max_iterations=max(base.ai_agent_max_iterations, 6),
        ai_agent_max_tool_calls=max(base.ai_agent_max_tool_calls, 5),
        ai_agent_max_repeated_actions=base.ai_agent_max_repeated_actions,
        ai_agent_max_external_sync_candidates=max(
            base.ai_agent_max_external_sync_candidates,
            3,
        ),
        ai_rate_limit_per_minute=max(base.ai_rate_limit_per_minute, 20),
        rag_prompt_version=base.rag_prompt_version,
        openai_api_key=base.openai_api_key,
        openai_base_url=base.openai_base_url,
        law_open_api_oc=base.law_open_api_oc,
        law_open_api_base_url=base.law_open_api_base_url,
        law_open_api_service_url=base.law_open_api_service_url,
        frontend_origin=FRONTEND_ORIGIN,
        frontend_extra_origins="",
        auth_cookie_secure=False,
    )


@contextmanager
def _client_context(settings: Settings) -> Generator[LiveApiContext, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    def override_get_settings() -> Settings:
        return settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    with TestClient(app) as test_client:
        yield LiveApiContext(
            client=test_client,
            session_factory=testing_session_local,
        )
    app.dependency_overrides.clear()


def _post_json(client: TestClient, path: str, payload: dict[str, object]) -> dict:
    response = client.post(path, json=payload, headers=origin_headers())
    assert response.status_code == 200, response.text
    return response.json()


def _evaluate_quality(
    search_body: dict[str, Any],
    issues_body: dict[str, Any],
    draft_body: dict[str, Any],
) -> dict[str, Any]:
    search_items = search_body.get("items") or []
    issues_text = str(issues_body.get("issues_text") or "")
    draft_text = str(draft_body.get("draft") or "")
    all_text = "\n".join(
        [
            _format_search_items(search_items),
            issues_text,
            draft_text,
        ]
    )
    missing_required_refs = [
        f"{law_title} {article_no}"
        for law_title, article_no in REQUIRED_SEARCH_REFS
        if not _search_items_contain_ref(search_items, law_title, article_no)
    ]
    missing_optional_refs = [
        f"{law_title} {article_no}"
        for law_title, article_no in IMPORTANT_OPTIONAL_REFS
        if not _search_items_contain_ref(search_items, law_title, article_no)
    ]
    issue_coverage = {
        "death_liability": _contains_any(
            issues_text,
            ("과실치사", "사망", "죽", "과실"),
        ),
        "corpse_concealment": _contains_any(
            issues_text,
            ("사체", "시체", "은닉", "매장", "유기"),
        ),
        "self_surrender": _contains_any(issues_text, ("자수", "감경")),
        "proof_or_investigation": _contains_any(
            issues_text,
            ("입증", "수사", "시신 미발견", "피해자", "신원"),
        ),
    }
    draft_coverage = {
        "death_liability": _contains_any(
            draft_text,
            ("과실치사", "사망", "죽", "과실"),
        ),
        "corpse_concealment": _contains_any(
            draft_text,
            ("사체", "시체", "은닉", "매장", "유기"),
        ),
        "self_surrender": _contains_any(draft_text, ("자수", "감경")),
        "proof_or_investigation": _contains_any(
            draft_text,
            ("입증", "수사", "시신", "피해자", "신원"),
        ),
    }
    return {
        "search_item_count": len(search_items),
        "missing_required_search_refs": missing_required_refs,
        "missing_optional_search_refs": missing_optional_refs,
        "forbidden_phrase_hits": [
            phrase for phrase in FORBIDDEN_PHRASES if phrase in all_text
        ],
        "chatbot_tail_hits": [
            phrase for phrase in CHATBOT_TAIL_PHRASES if phrase in draft_text
        ],
        "article_mismatch_hits": _article_mismatch_hits(issues_text, draft_text),
        "irrelevant_article_hits": _irrelevant_article_hits(all_text),
        "issue_coverage": issue_coverage,
        "issue_coverage_passed": all(issue_coverage.values()),
        "draft_coverage": draft_coverage,
        "draft_coverage_passed": all(draft_coverage.values()),
    }


def _print_live_report(
    search_body: dict[str, Any],
    issues_body: dict[str, Any],
    draft_body: dict[str, Any],
    quality: dict[str, Any],
) -> None:
    print("\n[LIVE RAG QUALITY REPORT]")
    print(f"search_run_id={search_body.get('run_id')}")
    print(f"search_item_count={len(search_body.get('items') or [])}")
    print("[search_results]")
    for item in (search_body.get("items") or [])[:20]:
        print(
            f"- #{item.get('rank')} {item.get('title')} "
            f"{item.get('heading')} score={item.get('score'):.3f}"
        )
    print("[issues_excerpt]")
    print(_excerpt(str(issues_body.get("issues_text") or ""), limit=2500))
    print("[draft_excerpt]")
    print(_excerpt(str(draft_body.get("draft") or ""), limit=2500))
    print("[quality]")
    print(quality)


def _format_search_items(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{item.get('title')} {item.get('heading')} {item.get('content')}"
        for item in items
    )


def _search_items_contain_ref(
    items: list[dict[str, Any]],
    law_title: str,
    article_no: str,
) -> bool:
    normalized_law_title = _normalize_match_text(law_title)
    normalized_article_no = _normalize_match_text(article_no)
    for item in items:
        title = _normalize_match_text(str(item.get("title") or ""))
        if normalized_law_title not in title:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metadata_article_no = _normalize_match_text(
            str(metadata.get("article_no") or "")
        )
        heading = _normalize_match_text(str(item.get("heading") or ""))
        content_prefix = _normalize_match_text(str(item.get("content") or "")[:300])
        if (
            metadata_article_no == normalized_article_no
            or normalized_article_no in heading
            or normalized_article_no in content_prefix
        ):
            return True
    return False


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _article_mismatch_hits(*texts: str) -> list[str]:
    hits: list[str] = []
    for text in texts:
        if "제51조" in text and "자수" in text:
            hits.append("자수 효과를 형법 제51조로 잘못 연결")
    return hits


def _irrelevant_article_hits(text: str) -> list[str]:
    hits: list[str] = []
    if "제151조" in text or "범인은닉" in text:
        hits.append("제3자 범인 은닉 사실이 없는데 형법 제151조를 언급")
    return hits


def _normalize_match_text(value: str) -> str:
    return "".join(value.split()).lower()


def _excerpt(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def origin_headers(origin: str = FRONTEND_ORIGIN) -> dict[str, str]:
    return {"Origin": origin}


def register_and_login(
    client: TestClient,
    *,
    email: str,
) -> dict:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "nickname": email.split("@")[0],
        },
        headers=origin_headers(),
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
        headers=origin_headers(),
    )
    assert login_response.status_code == 200
    return login_response.json()
