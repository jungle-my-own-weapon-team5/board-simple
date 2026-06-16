import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.post import Post

logger = logging.getLogger(__name__)

Source = Literal["top", "best", "new", "search"]

HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
HN_LIST_URLS: dict[str, str] = {
    "top": "https://hacker-news.firebaseio.com/v0/topstories.json",
    "best": "https://hacker-news.firebaseio.com/v0/beststories.json",
    "new": "https://hacker-news.firebaseio.com/v0/newstories.json",
}
ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
HACKER_NEWS_ITEM_WEB_URL = "https://news.ycombinator.com/item?id={item_id}"


@dataclass
class HackerNewsStory:
    hn_id: int
    title: str
    url: str | None
    hn_url: str
    author: str | None = None
    points: int | None = None
    comment_count: int | None = None
    created_at: datetime | None = None


@dataclass
class HackerNewsSummary:
    summary: str
    key_points: list[str]


@dataclass
class HackerNewsCandidate:
    hn_id: int
    title: str
    url: str | None
    hn_url: str
    author: str | None
    points: int | None
    comment_count: int | None
    created_at: datetime | None
    summary_status: str
    summary: str | None
    key_points: list[str]
    is_imported: bool
    error: str | None


class HackerNewsService:
    def __init__(self, settings: Settings | None = None, timeout: float = 10.0) -> None:
        self.settings = settings or get_settings()
        self.timeout = timeout
        self._llm = None

    def preview(
        self,
        db: Session,
        source: Source,
        query: str | None,
        limit: int,
    ) -> list[HackerNewsCandidate]:
        stories = self.fetch_stories(source, query, limit)
        imported_ids = self.imported_ids(db, [story.hn_id for story in stories])
        return [self._candidate_for_story(story, story.hn_id in imported_ids) for story in stories]

    def imported_ids(self, db: Session, hn_ids: list[int]) -> set[int]:
        if not hn_ids:
            return set()
        rows = db.scalars(
            select(Post.source_id).where(
                Post.source_type == "hacker_news",
                Post.source_id.in_([str(hn_id) for hn_id in hn_ids]),
            )
        ).all()
        return {int(source_id) for source_id in rows if source_id is not None}

    def fetch_stories(self, source: Source, query: str | None, limit: int) -> list[HackerNewsStory]:
        if source == "search":
            return self._fetch_algolia_stories(query or "", limit)
        return self._fetch_firebase_stories(source, limit)

    def _candidate_for_story(
        self,
        story: HackerNewsStory,
        is_imported: bool,
    ) -> HackerNewsCandidate:
        if is_imported:
            return self._failed_candidate(story, "already_imported", True)
        if not story.url:
            return self._failed_candidate(story, "original_url_missing", False)

        try:
            article_text = self.extract_article_text(story.url)
            summary = self.summarize_article(story.title, story.url, article_text)
        except Exception as exc:
            return self._failed_candidate(story, str(exc), False)

        return HackerNewsCandidate(
            hn_id=story.hn_id,
            title=story.title,
            url=story.url,
            hn_url=story.hn_url,
            author=story.author,
            points=story.points,
            comment_count=story.comment_count,
            created_at=story.created_at,
            summary_status="success",
            summary=summary.summary,
            key_points=summary.key_points,
            is_imported=False,
            error=None,
        )

    def _failed_candidate(
        self,
        story: HackerNewsStory,
        error: str,
        is_imported: bool,
    ) -> HackerNewsCandidate:
        return HackerNewsCandidate(
            hn_id=story.hn_id,
            title=story.title,
            url=story.url,
            hn_url=story.hn_url,
            author=story.author,
            points=story.points,
            comment_count=story.comment_count,
            created_at=story.created_at,
            summary_status="failed",
            summary=None,
            key_points=[],
            is_imported=is_imported,
            error=error,
        )

    def _fetch_firebase_stories(self, source: Source, limit: int) -> list[HackerNewsStory]:
        payload = self._get_json(HN_LIST_URLS[source])
        item_ids = [int(item_id) for item_id in payload[:limit]]
        stories: list[HackerNewsStory] = []
        for item_id in item_ids:
            try:
                item = self._get_json(HN_ITEM_URL.format(item_id=item_id))
            except Exception:
                continue
            story = self._story_from_firebase_item(item)
            if story is not None:
                stories.append(story)
        return stories

    def _fetch_algolia_stories(self, query: str, limit: int) -> list[HackerNewsStory]:
        payload = self._get_json(
            ALGOLIA_SEARCH_URL,
            params={"query": query, "tags": "story", "hitsPerPage": limit},
        )
        stories: list[HackerNewsStory] = []
        for hit in payload.get("hits", []):
            story = self._story_from_algolia_hit(hit)
            if story is not None:
                stories.append(story)
        return stories[:limit]

    def _get_json(self, url: str, params: dict[str, object] | None = None) -> Any:
        import httpx

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def extract_article_text(self, url: str) -> str:
        import httpx
        from bs4 import BeautifulSoup
        from readability import Document

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()

        readable = Document(response.text).summary()
        text = BeautifulSoup(readable, "html.parser").get_text("\n", strip=True)
        text = "\n".join(line for line in text.splitlines() if line.strip())
        if len(text) < 200:
            raise ValueError("article_text_too_short")
        return text[:12000]

    def summarize_article(self, title: str, url: str, article_text: str) -> HackerNewsSummary:
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")

        if self.settings.news_llm_debug:
            logger.info(
                "HN LLM request model=%s title=%r url=%s article_chars=%s",
                self.settings.openai_chat_model,
                title,
                url,
                len(article_text),
            )

        response = self._get_llm().invoke(
            [
                (
                    "system",
                    "당신은 기술 뉴스 편집자입니다. 기사 전체를 번역하지 말고 "
                    "한국어 요약 1문단과 핵심 포인트 3~5개만 JSON으로 작성하세요. "
                    'JSON 형식은 {"summary": "...", "key_points": ["..."]} 입니다.',
                ),
                (
                    "human",
                    f"제목: {title}\n원문 URL: {url}\n\n본문:\n{article_text}",
                ),
            ]
        )
        content = _message_text(response.content)
        summary = self._parse_summary(content)
        if self.settings.news_llm_debug:
            logger.info(
                "HN LLM response model=%s response_chars=%s summary_chars=%s key_points=%s",
                self.settings.openai_chat_model,
                len(content),
                len(summary.summary),
                len(summary.key_points),
            )
        return summary

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_chat_model,
            )
        return self._llm

    def _parse_summary(self, content: str) -> HackerNewsSummary:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        payload = json.loads(text)
        summary = str(payload.get("summary", "")).strip()
        key_points = [
            str(point).strip()
            for point in payload.get("key_points", [])
            if str(point).strip()
        ]
        if not summary or not key_points:
            raise ValueError("summary_generation_failed")
        return HackerNewsSummary(summary=summary, key_points=key_points[:5])

    def _story_from_firebase_item(self, item: dict[str, Any]) -> HackerNewsStory | None:
        if item.get("type") != "story" or not item.get("id") or not item.get("title"):
            return None
        return HackerNewsStory(
            hn_id=int(item["id"]),
            title=str(item["title"]),
            url=item.get("url"),
            hn_url=HACKER_NEWS_ITEM_WEB_URL.format(item_id=item["id"]),
            author=item.get("by"),
            points=item.get("score"),
            comment_count=item.get("descendants"),
            created_at=_from_unix(item.get("time")),
        )

    def _story_from_algolia_hit(self, hit: dict[str, Any]) -> HackerNewsStory | None:
        object_id = hit.get("objectID")
        title = hit.get("title") or hit.get("story_title")
        if not object_id or not title:
            return None
        return HackerNewsStory(
            hn_id=int(object_id),
            title=str(title),
            url=hit.get("url") or hit.get("story_url"),
            hn_url=HACKER_NEWS_ITEM_WEB_URL.format(item_id=object_id),
            author=hit.get("author"),
            points=hit.get("points"),
            comment_count=hit.get("num_comments"),
            created_at=_from_iso(hit.get("created_at")),
        )


def build_hacker_news_post_content(
    summary: str,
    key_points: list[str],
    url: str | None,
    hn_url: str,
) -> str:
    point_lines = "\n".join(f"- {point}" for point in key_points)
    source_lines = [f"- Hacker News: {hn_url}"]
    if url:
        source_lines.insert(0, f"- 원문: {url}")
    return (
        "## 한국어 요약\n\n"
        f"{summary}\n\n"
        "## 핵심 포인트\n\n"
        f"{point_lines}\n\n"
        "## 원문\n\n"
        f"{chr(10).join(source_lines)}\n\n"
        "#hackernews #technews"
    )


def truncate_title(title: str) -> str:
    compact = " ".join(title.split())
    return compact[:200] or "Hacker News"


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return str(content)


def _from_unix(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _from_iso(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


_hacker_news_service: HackerNewsService | None = None


def get_hacker_news_service() -> HackerNewsService:
    global _hacker_news_service
    if _hacker_news_service is None:
        _hacker_news_service = HackerNewsService()
    return _hacker_news_service
