from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.models.ai import DiscussionTopicRecord
from app.models.post import Post
from app.schemas.admin import DiscussionTopicUpdate
from app.schemas.ai import DiscussionTopic, RagCitation
from app.services.ai_demo import get_discussion_topics as get_demo_discussion_topics
from app.services.ai_runtime import _extract_json, _generate_text, search_rag
from app.services.tags import normalize_tag_names

TOPIC_COUNT = 3
RECENT_DAYS = 14
GENERIC_TOPIC_KEYWORDS = {
    "조선",
    "역사",
    "토론",
    "오늘",
    "떡밥",
    "질문",
    "발견",
    "사료",
    "해석",
    "요청",
    "가벼운",
    "생활사",
    "문화",
    "정치",
    "외교",
    "전쟁",
    "인물",
    "열전",
    "사건",
    "사고",
    "재평가",
    "평가",
    "왕실",
    "왕권",
    "권력",
    "다르게",
    "보면",
    "어떤",
    "쟁점이",
    "될까",
    "당시의",
    "명분과",
    "결과",
    "중요하게",
    "봐야",
    "할까요",
    "주제를",
    "평가할",
    "가장",
    "먼저",
    "확인해야",
    "근거는",
    "무엇일까요",
    "대해",
    "다시",
    "토론해봅시다",
}


def get_public_discussion_topics(
    db: Session,
    settings: Settings,
    topic_date: date | None = None,
) -> list[DiscussionTopic]:
    target_date = topic_date or date.today()
    _ensure_daily_topics(db, settings, target_date)
    pinned = db.scalars(
        select(DiscussionTopicRecord)
        .where(DiscussionTopicRecord.is_pinned.is_(True))
        .where(DiscussionTopicRecord.is_hidden.is_(False))
        .order_by(DiscussionTopicRecord.updated_at.desc(), DiscussionTopicRecord.id.desc())
        .limit(TOPIC_COUNT)
    ).all()
    remaining = max(TOPIC_COUNT - len(pinned), 0)
    daily = []
    if remaining:
        daily = db.scalars(
            select(DiscussionTopicRecord)
            .where(DiscussionTopicRecord.topic_date == target_date)
            .where(DiscussionTopicRecord.is_pinned.is_(False))
            .where(DiscussionTopicRecord.is_hidden.is_(False))
            .order_by(DiscussionTopicRecord.score.desc(), DiscussionTopicRecord.id.asc())
            .limit(remaining)
        ).all()
    return [_serialize_topic(record) for record in [*pinned, *daily]]


def list_admin_discussion_topics(
    db: Session,
    settings: Settings,
    topic_date: date | None = None,
) -> list[DiscussionTopic]:
    target_date = topic_date or date.today()
    _ensure_daily_topics(db, settings, target_date)
    records = db.scalars(
        select(DiscussionTopicRecord)
        .where(DiscussionTopicRecord.topic_date == target_date)
        .order_by(
            DiscussionTopicRecord.is_pinned.desc(),
            DiscussionTopicRecord.is_hidden.asc(),
            DiscussionTopicRecord.score.desc(),
            DiscussionTopicRecord.id.asc(),
        )
    ).all()
    return [_serialize_topic(record) for record in records]


def refresh_discussion_topics(
    db: Session,
    settings: Settings,
    topic_date: date | None = None,
) -> list[DiscussionTopic]:
    target_date = topic_date or date.today()
    for record in db.scalars(
        select(DiscussionTopicRecord)
        .where(DiscussionTopicRecord.topic_date == target_date)
        .where(DiscussionTopicRecord.is_pinned.is_(False))
    ).all():
        db.delete(record)
    db.commit()
    _ensure_daily_topics(db, settings, target_date)
    return list_admin_discussion_topics(db, settings, target_date)


def update_discussion_topic(
    db: Session,
    topic_id: int,
    payload: DiscussionTopicUpdate,
) -> DiscussionTopic:
    record = db.get(DiscussionTopicRecord, topic_id)
    if record is None:
        raise ValueError("Discussion topic not found")

    data = payload.model_dump(exclude_unset=True)
    if "tags" in data:
        record.tags_json = json.dumps(normalize_tag_names(data.pop("tags") or []), ensure_ascii=False)

    for key, value in data.items():
        if value is not None:
            setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return _serialize_topic(record)


def _ensure_daily_topics(db: Session, settings: Settings, topic_date: date) -> None:
    _remove_duplicate_daily_topics(db, topic_date)
    visible_count = len(
        db.scalars(
            select(DiscussionTopicRecord.id)
            .where(DiscussionTopicRecord.topic_date == topic_date)
            .where(DiscussionTopicRecord.is_hidden.is_(False))
        ).all()
    )
    if visible_count >= TOPIC_COUNT:
        return

    existing_titles = set(
        db.scalars(select(DiscussionTopicRecord.title).where(DiscussionTopicRecord.topic_date == topic_date)).all()
    )
    existing_topic_keys: set[str] = set()
    for record in db.scalars(select(DiscussionTopicRecord).where(DiscussionTopicRecord.topic_date == topic_date)).all():
        topic = _topic_dict_from_record(record)
        if _should_dedupe_topic_keys(topic):
            existing_topic_keys.update(_topic_dedupe_keys(topic))

    topics = _generate_topics(db, settings, topic_date)
    added = 0
    for topic in topics:
        if topic["title"] in existing_titles:
            continue
        topic_keys = _topic_dedupe_keys(topic)
        should_dedupe_keys = _should_dedupe_topic_keys(topic)
        if should_dedupe_keys and topic_keys & existing_topic_keys:
            continue
        db.add(_record_from_topic(topic_date, topic))
        existing_titles.add(topic["title"])
        if should_dedupe_keys:
            existing_topic_keys.update(topic_keys)
        added += 1
        if visible_count + added >= TOPIC_COUNT:
            break
    if added:
        db.commit()


def _remove_duplicate_daily_topics(db: Session, topic_date: date) -> None:
    records = db.scalars(
        select(DiscussionTopicRecord)
        .where(DiscussionTopicRecord.topic_date == topic_date)
        .where(DiscussionTopicRecord.is_hidden.is_(False))
        .order_by(
            DiscussionTopicRecord.is_pinned.desc(),
            DiscussionTopicRecord.score.desc(),
            DiscussionTopicRecord.updated_at.desc(),
            DiscussionTopicRecord.id.asc(),
        )
    ).all()

    seen_keys: set[str] = set()
    changed = False
    for record in records:
        topic = _topic_dict_from_record(record)
        if not _should_dedupe_topic_keys(topic):
            continue
        keys = _topic_dedupe_keys(topic)
        if keys & seen_keys and not record.is_pinned:
            db.delete(record)
            changed = True
            continue
        seen_keys.update(keys)
    if changed:
        db.commit()


def _generate_topics(db: Session, settings: Settings, topic_date: date) -> list[dict[str, Any]]:
    candidates = _reaction_candidates(db)
    if not candidates:
        return _fallback_demo_topics(db, settings, topic_date)

    enriched = [_enrich_candidate_with_rag(db, settings, candidate) for candidate in candidates[:6]]
    generated: list[dict[str, Any]] = []
    if settings.openai_api_key:
        llm_topics = _generate_llm_topics(settings, topic_date, enriched)
        if llm_topics:
            generated = llm_topics
    if not generated:
        generated = [_local_topic_from_candidate(item, "local") for item in enriched]
    generated = _dedupe_topics(generated)
    if len(generated) < TOPIC_COUNT:
        seen_titles = {item["title"] for item in generated}
        seen_keys = set().union(*(_topic_dedupe_keys(item) for item in generated)) if generated else set()
        for fallback in _fallback_demo_topics(db, settings, topic_date):
            if fallback["title"] in seen_titles:
                continue
            fallback_keys = _topic_dedupe_keys(fallback)
            if _should_dedupe_topic_keys(fallback) and fallback_keys & seen_keys:
                continue
            generated.append(fallback)
            seen_titles.add(fallback["title"])
            if _should_dedupe_topic_keys(fallback):
                seen_keys.update(fallback_keys)
            if len(generated) >= TOPIC_COUNT:
                break
    return generated[:TOPIC_COUNT]


def _reaction_candidates(db: Session) -> list[dict[str, Any]]:
    cutoff = datetime.now() - timedelta(days=RECENT_DAYS)
    posts = db.scalars(
        select(Post)
        .where(Post.created_at >= cutoff)
        .options(selectinload(Post.tags), selectinload(Post.author))
        .order_by(Post.comment_count.desc(), Post.view_count.desc(), Post.created_at.desc())
        .limit(30)
    ).all()
    if not posts:
        posts = db.scalars(
            select(Post)
            .options(selectinload(Post.tags), selectinload(Post.author))
            .order_by(Post.comment_count.desc(), Post.view_count.desc(), Post.created_at.desc())
            .limit(30)
        ).all()

    candidates = []
    for post in posts:
        age_days = max((datetime.now(post.created_at.tzinfo) - post.created_at).days, 0) if post.created_at else 0
        recency_bonus = max(RECENT_DAYS - age_days, 0)
        score = post.comment_count * 5 + post.view_count * 0.7 + recency_bonus + (2 if post.ai_search_summary else 0)
        candidates.append(
            {
                "post": post,
                "score": float(score),
                "tags": [tag.name for tag in post.tags],
                "query": _topic_rag_query(post),
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def _topic_rag_query(post: Post) -> str:
    tags = ", ".join(tag.name for tag in post.tags)
    return "\n".join(
        [
            post.title,
            f"글 유형: {post.post_type}",
            f"카테고리: {post.category}",
            f"태그: {tags or '없음'}",
            post.ai_search_summary or _clean_text(post.content)[:800],
        ]
    ).strip()


def _enrich_candidate_with_rag(
    db: Session,
    settings: Settings,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    try:
        rag = search_rag(db, settings, candidate["query"], 2)
        citations = [citation.model_dump() for citation in rag.citations]
        evidence_summary = rag.answer_summary
    except Exception:
        citations = []
        evidence_summary = ""
    return {**candidate, "citations": citations, "evidence_summary": evidence_summary}


def _generate_llm_topics(
    settings: Settings,
    topic_date: date,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = []
    for item in candidates:
        post = item["post"]
        payload.append(
            {
                "post_id": post.id,
                "title": post.title,
                "content_summary": post.ai_search_summary or _clean_text(post.content)[:500],
                "post_type": post.post_type,
                "category": post.category,
                "tags": item["tags"],
                "comment_count": post.comment_count,
                "view_count": post.view_count,
                "score": item["score"],
                "citations": item["citations"],
                "evidence_summary": item["evidence_summary"],
            }
        )

    prompt = (
        "너는 조선시대 역사 커뮤니티의 오늘의 토론거리 편집자다. "
        "게시글/댓글 반응과 RAG citation을 근거로 오늘 홈 화면에 노출할 토론거리 3개를 생성해라. "
        "과장하지 말고, 근거가 약한 주제는 질문형으로 다뤄라. "
        "JSON만 반환한다. 스키마: "
        '{"topics":[{"source":"","title":"","summary":"","question":"","reason":"","tags":[""],'
        '"draft_title":"","draft_content":"","draft_post_type":"토론","draft_category":"오늘의 떡밥",'
        '"basis_post_id":1,"score":1.0,"citations":[{"id":"","title":"","period":"","summary":"","relevance":0,"source_url":""}]}]}\n'
        f"날짜: {topic_date.isoformat()}\n"
        f"후보: {json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        data = _extract_json(_generate_text(settings, prompt))
        topics = data.get("topics", [])
        normalized = [_normalize_generated_topic(item, "llm") for item in topics]
        return normalized[:TOPIC_COUNT]
    except Exception:
        return []


def _local_topic_from_candidate(item: dict[str, Any], generation_source: str) -> dict[str, Any]:
    post: Post = item["post"]
    clean_content = _clean_text(post.content)
    tags = normalize_tag_names(item["tags"] or [post.category, post.post_type])
    citations = _valid_citations(item.get("citations", []))
    citation_hint = f" RAG 근거 {len(citations)}건을 함께 확인했습니다." if citations else " 아직 직접 citation은 약합니다."
    return _normalize_generated_topic(
        {
            "source": "게시판 반응 + RAG",
            "title": f"{post.title}, 다르게 보면 어떤 쟁점이 될까?",
            "summary": (post.ai_search_summary or clean_content[:180] or "게시판 반응이 있는 주제를 다시 토론거리로 정리했습니다."),
            "question": _question_for_category(post.category),
            "reason": f"댓글 {post.comment_count}개, 조회 {post.view_count}회를 바탕으로 선정했습니다.{citation_hint}",
            "tags": tags[:5],
            "draft_title": f"{post.title}에 대해 다시 토론해봅시다",
            "draft_content": _draft_content(post, citations),
            "draft_post_type": "토론",
            "draft_category": post.category,
            "basis_post_id": post.id,
            "score": item["score"],
            "citations": citations,
        },
        generation_source,
    )


def _fallback_demo_topics(db: Session, settings: Settings, topic_date: date) -> list[dict[str, Any]]:
    topics = []
    for demo in get_demo_discussion_topics():
        try:
            rag = search_rag(db, settings, f"{demo.title}\n{demo.summary}\n{demo.question}", 2)
            citations = [citation.model_dump() for citation in rag.citations]
        except Exception:
            citations = []
        topics.append(
            _normalize_generated_topic(
                {
                    "source": demo.source,
                    "title": demo.title,
                    "summary": demo.summary,
                    "question": demo.question,
                    "reason": f"{demo.reason} 날짜 {topic_date.isoformat()} 기준 기본 추천입니다.",
                    "tags": demo.tags,
                    "draft_title": demo.title,
                    "draft_content": f"{demo.summary}\n\n{demo.question}\n\n여러분은 어떤 근거를 더 중요하게 보시나요?",
                    "draft_post_type": "토론",
                    "draft_category": "오늘의 떡밥",
                    "basis_post_id": None,
                    "score": 1.0,
                    "citations": citations,
                },
                "fallback",
            )
        )
    return topics


def _normalize_generated_topic(raw: dict[str, Any], generation_source: str) -> dict[str, Any]:
    title = str(raw.get("title") or "오늘의 역사 토론거리").strip()[:200]
    draft_title = str(raw.get("draft_title") or title).strip()[:200]
    tags = normalize_tag_names([str(tag) for tag in raw.get("tags", []) if str(tag).strip()])[:5]
    return {
        "source": str(raw.get("source") or "AI 추천").strip()[:80],
        "title": title,
        "summary": str(raw.get("summary") or title).strip(),
        "question": str(raw.get("question") or "이 주제를 어떤 기준으로 평가할 수 있을까요?").strip(),
        "reason": str(raw.get("reason") or "게시판 반응과 RAG 근거를 함께 참고했습니다.").strip(),
        "tags": tags or ["조선", "토론"],
        "draft_title": draft_title,
        "draft_content": str(raw.get("draft_content") or raw.get("summary") or title).strip(),
        "draft_post_type": str(raw.get("draft_post_type") or "토론").strip()[:20],
        "draft_category": str(raw.get("draft_category") or "오늘의 떡밥").strip()[:50],
        "basis_post_id": _optional_int(raw.get("basis_post_id")),
        "score": float(raw.get("score") or 0.0),
        "citations": _valid_citations(raw.get("citations", [])),
        "generation_source": generation_source,
    }


def _record_from_topic(topic_date: date, topic: dict[str, Any]) -> DiscussionTopicRecord:
    return DiscussionTopicRecord(
        topic_date=topic_date,
        source=topic["source"],
        title=topic["title"],
        summary=topic["summary"],
        question=topic["question"],
        reason=topic["reason"],
        tags_json=json.dumps(topic["tags"], ensure_ascii=False),
        draft_title=topic["draft_title"],
        draft_content=topic["draft_content"],
        draft_post_type=topic["draft_post_type"],
        draft_category=topic["draft_category"],
        citations_json=json.dumps(topic["citations"], ensure_ascii=False),
        basis_post_id=topic.get("basis_post_id"),
        score=topic["score"],
        generation_source=topic["generation_source"],
    )


def _serialize_topic(record: DiscussionTopicRecord) -> DiscussionTopic:
    return DiscussionTopic(
        id=record.id,
        topic_date=record.topic_date,
        source=record.source,
        title=record.title,
        summary=record.summary,
        question=record.question,
        reason=record.reason,
        tags=_json_list(record.tags_json),
        draft_title=record.draft_title,
        draft_content=record.draft_content,
        draft_post_type=record.draft_post_type,
        draft_category=record.draft_category,
        citations=[RagCitation.model_validate(item) for item in _json_list(record.citations_json)],
        is_pinned=record.is_pinned,
        is_hidden=record.is_hidden,
    )


def _dedupe_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen_titles: set[str] = set()
    seen_keys: set[str] = set()
    for topic in sorted(topics, key=lambda item: float(item.get("score") or 0.0), reverse=True):
        title = str(topic.get("title") or "").strip()
        keys = _topic_dedupe_keys(topic)
        if title in seen_titles or keys & seen_keys:
            continue
        deduped.append(topic)
        seen_titles.add(title)
        seen_keys.update(keys)
        if len(deduped) >= TOPIC_COUNT:
            break
    return deduped


def _topic_dedupe_keys(topic: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    basis_post_id = _optional_int(topic.get("basis_post_id"))
    if basis_post_id is not None:
        keys.add(f"post:{basis_post_id}")

    for tag in topic.get("tags") or []:
        normalized = _normalize_topic_keyword(str(tag))
        if _is_distinct_topic_keyword(normalized):
            keys.add(f"kw:{normalized}")
    return keys


def _topic_dict_from_record(record: DiscussionTopicRecord) -> dict[str, Any]:
    return {
        "title": record.title,
        "summary": record.summary,
        "question": record.question,
        "draft_title": record.draft_title,
        "tags": _json_list(record.tags_json),
        "basis_post_id": record.basis_post_id,
        "generation_source": record.generation_source,
    }


def _normalize_topic_keyword(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.strip().lower())


def _should_dedupe_topic_keys(topic: dict[str, Any]) -> bool:
    return topic.get("generation_source") != "fallback"


def _is_distinct_topic_keyword(value: str) -> bool:
    if len(value) < 2 or value in GENERIC_TOPIC_KEYWORDS:
        return False
    if value.endswith(("인가", "일까", "될까", "보자", "토론해봅시다")):
        return False
    return True


def _valid_citations(raw_citations: Any) -> list[dict[str, Any]]:
    citations = []
    if not isinstance(raw_citations, list):
        return []
    for item in raw_citations[:3]:
        try:
            citations.append(RagCitation.model_validate(item).model_dump())
        except Exception:
            continue
    return citations


def _json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _clean_text(value: str) -> str:
    value = re.sub(r"```[\s\S]*?```", " ", value)
    value = re.sub(r"[#>*_~`|-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _question_for_category(category: str) -> str:
    if category == "왕과 권력":
        return "당시의 명분과 결과 중 어느 쪽을 더 중요하게 봐야 할까요?"
    if category == "생활사와 문화":
        return "이 주제를 생활사와 통치 체계 중 어느 관점에서 보면 더 설득력 있을까요?"
    if category == "전쟁과 외교":
        return "현실적 선택과 도덕적 평가를 어떻게 나눠 볼 수 있을까요?"
    return "이 주제를 평가할 때 가장 먼저 확인해야 할 근거는 무엇일까요?"


def _draft_content(post: Post, citations: list[dict[str, Any]]) -> str:
    citation_lines = "\n".join(f"- {item['title']}: {item['summary'][:140]}" for item in citations[:2])
    basis = f"\n\n참고할 RAG 근거:\n{citation_lines}" if citation_lines else ""
    return (
        f"{post.title}에 대해 다시 이야기해보고 싶습니다.\n\n"
        f"{_clean_text(post.content)[:500]}\n\n"
        f"이 주제를 볼 때 단순한 호불호보다 당시의 제도, 인물의 선택지, 후대의 평가를 나눠 보면 좋겠습니다."
        f"{basis}\n\n"
        f"{_question_for_category(post.category)}"
    ).strip()
