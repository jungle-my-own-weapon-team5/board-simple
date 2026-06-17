import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.post import Post
from app.schemas.news import (
    DuplicateMatch,
    NewsDuplicateJudgementItem,
    NewsDuplicateJudgementResponseItem,
    NewsDuplicateJudgementResult,
)

logger = logging.getLogger(__name__)

FALLBACK_REASONS = {
    "same_url": "같은 원문 URL입니다.",
    "similar_title": "제목이 유사하지만 실제 중복 여부는 확인이 필요합니다.",
    "rag": "벡터 검색상 유사하지만 실제 중복 여부는 확인이 필요합니다.",
}
VALID_VERDICTS = {"duplicate", "not_duplicate", "uncertain"}


class DuplicateJudgementService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._llm = None

    def judge(
        self,
        db: Session,
        items: list[NewsDuplicateJudgementItem],
    ) -> list[NewsDuplicateJudgementResponseItem]:
        posts_by_id = self._load_posts(db, items)
        return [self._judge_item(item, posts_by_id) for item in items]

    def _load_posts(
        self,
        db: Session,
        items: list[NewsDuplicateJudgementItem],
    ) -> dict[int, Post]:
        post_ids = {
            match.post_id
            for item in items
            for match in item.duplicate_matches
        }
        if not post_ids:
            return {}
        posts = db.scalars(select(Post).where(Post.id.in_(post_ids))).all()
        return {post.id: post for post in posts}

    def _judge_item(
        self,
        item: NewsDuplicateJudgementItem,
        posts_by_id: dict[int, Post],
    ) -> NewsDuplicateJudgementResponseItem:
        matches = self._existing_unique_matches(item.duplicate_matches, posts_by_id)
        if not matches:
            return NewsDuplicateJudgementResponseItem(client_id=item.client_id, results=[])
        if not self.settings.openai_api_key:
            return NewsDuplicateJudgementResponseItem(
                client_id=item.client_id,
                results=[self._fallback_result(match, posts_by_id[match.post_id]) for match in matches],
            )
        try:
            results = self._judge_with_llm(item, matches, posts_by_id)
        except Exception:
            logger.exception("Failed to judge news duplicates with LLM")
            results = {}
        return NewsDuplicateJudgementResponseItem(
            client_id=item.client_id,
            results=[
                results.get(match.post_id)
                or self._fallback_result(match, posts_by_id[match.post_id])
                for match in matches
            ],
        )

    def _judge_with_llm(
        self,
        item: NewsDuplicateJudgementItem,
        matches: list[DuplicateMatch],
        posts_by_id: dict[int, Post],
    ) -> dict[int, NewsDuplicateJudgementResult]:
        response = self._get_llm().invoke(
            [
                (
                    "system",
                    "당신은 뉴스 편집자입니다. 제공된 후보 뉴스와 기존 게시글만 비교해 "
                    "실제 중복 여부를 JSON 배열로만 답하세요. verdict는 duplicate, "
                    "not_duplicate, uncertain 중 하나입니다.",
                ),
                ("human", self._prompt(item, matches, posts_by_id)),
            ]
        )
        payload = _parse_json(_message_text(response.content))
        if not isinstance(payload, list):
            raise ValueError("duplicate_judgement_not_list")

        match_ids = {match.post_id for match in matches}
        results: dict[int, NewsDuplicateJudgementResult] = {}
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            try:
                post_id = int(raw.get("post_id"))
            except (TypeError, ValueError):
                continue
            verdict = str(raw.get("verdict") or "").strip()
            if post_id not in match_ids or verdict not in VALID_VERDICTS:
                continue
            confidence = raw.get("confidence")
            if confidence is not None:
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = None
            reason = str(raw.get("reason") or "").strip() or "판정 근거가 없습니다."
            post = posts_by_id[post_id]
            results[post_id] = NewsDuplicateJudgementResult(
                post_id=post_id,
                title=post.title,
                verdict=verdict,  # type: ignore[arg-type]
                confidence=confidence,
                reason=reason[:500],
            )
        return results

    def _prompt(
        self,
        item: NewsDuplicateJudgementItem,
        matches: list[DuplicateMatch],
        posts_by_id: dict[int, Post],
    ) -> str:
        existing = []
        for match in matches:
            post = posts_by_id[match.post_id]
            existing.append(
                {
                    "post_id": post.id,
                    "match_reason": match.reason,
                    "match_score": match.score,
                    "title": post.title,
                    "source_url": post.source_url,
                    "source_title": post.source_title,
                    "content_excerpt": post.content[:1600],
                }
            )
        return json.dumps(
            {
                "instruction": (
                    "같은 원문이거나 같은 사건/릴리즈/제품 발표를 사실상 같은 게시물로 "
                    "다시 게시하는 경우만 duplicate로 판단하세요. 관련은 있지만 초점이 "
                    "다르면 not_duplicate 또는 uncertain을 사용하세요."
                ),
                "candidate": {
                    "title": item.title,
                    "url": item.url,
                    "summary": item.summary,
                    "key_points": item.key_points,
                },
                "existing_posts": existing,
                "response_shape": [
                    {
                        "post_id": 1,
                        "verdict": "duplicate|not_duplicate|uncertain",
                        "confidence": 0.0,
                        "reason": "한국어 한 문장",
                    }
                ],
            },
            ensure_ascii=False,
        )

    def _existing_unique_matches(
        self,
        matches: list[DuplicateMatch],
        posts_by_id: dict[int, Post],
    ) -> list[DuplicateMatch]:
        seen: set[int] = set()
        unique: list[DuplicateMatch] = []
        for match in matches:
            if match.post_id in seen or match.post_id not in posts_by_id:
                continue
            seen.add(match.post_id)
            unique.append(match)
        return unique

    def _fallback_result(
        self,
        match: DuplicateMatch,
        post: Post,
    ) -> NewsDuplicateJudgementResult:
        return NewsDuplicateJudgementResult(
            post_id=post.id,
            title=post.title,
            verdict="duplicate" if match.reason == "same_url" else "uncertain",
            confidence=1.0 if match.reason == "same_url" else None,
            reason=FALLBACK_REASONS[match.reason],
        )

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_chat_model,
            )
        return self._llm


def _parse_json(content: str) -> object:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return str(content)


_duplicate_judgement_service: DuplicateJudgementService | None = None


def get_duplicate_judgement_service() -> DuplicateJudgementService:
    global _duplicate_judgement_service
    if _duplicate_judgement_service is None:
        _duplicate_judgement_service = DuplicateJudgementService()
    return _duplicate_judgement_service
