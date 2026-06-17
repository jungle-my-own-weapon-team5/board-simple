import hashlib
import json
import logging
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from app.core.config import Settings, get_settings
from app.services.duplicate_check import DuplicateMatchResult, normalize_url

logger = logging.getLogger(__name__)


@dataclass
class ArticleSummary:
    summary: str
    key_points: list[str]


@dataclass
class WebArticleCandidate:
    source_type: str
    source_id: str
    title: str
    url: str
    summary_status: str
    summary: str | None
    key_points: list[str]
    duplicate_matches: list[DuplicateMatchResult]
    error: str | None


class NewsCurationService:
    def __init__(self, settings: Settings | None = None, timeout: float = 10.0) -> None:
        self.settings = settings or get_settings()
        self.timeout = timeout
        self._llm = None

    def preview_web_article(
        self,
        url: str,
        duplicate_matches: list[DuplicateMatchResult],
        article_text: str | None = None,
    ) -> WebArticleCandidate:
        source_id = source_id_for_url(url)
        try:
            if article_text:
                title = title_from_url(url)
                text = article_text
            else:
                title, text = self.extract_article(url)
            summary = self.summarize_article(title, url, text)
        except Exception as exc:
            return WebArticleCandidate(
                source_type="web_article",
                source_id=source_id,
                title=title_from_url(url),
                url=url,
                summary_status="failed",
                summary=None,
                key_points=[],
                duplicate_matches=duplicate_matches,
                error=str(exc),
            )

        return WebArticleCandidate(
            source_type="web_article",
            source_id=source_id,
            title=title,
            url=url,
            summary_status="success",
            summary=summary.summary,
            key_points=summary.key_points,
            duplicate_matches=duplicate_matches,
            error=None,
        )

    def extract_article(self, url: str) -> tuple[str, str]:
        import httpx
        from bs4 import BeautifulSoup
        from readability import Document

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()

        document = Document(response.text)
        title = document.short_title() or title_from_url(url)
        readable = document.summary()
        text = BeautifulSoup(readable, "html.parser").get_text("\n", strip=True)
        text = "\n".join(line for line in text.splitlines() if line.strip())
        if len(text) < 200:
            raise ValueError("article_text_too_short")
        return title.strip()[:500] or title_from_url(url), text[:12000]

    def summarize_article(self, title: str, url: str, article_text: str) -> ArticleSummary:
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        response = self._get_llm().invoke(
            [
                (
                    "system",
                    "당신은 기술 뉴스 편집자입니다. 기사 전체를 번역하지 말고 "
                    "한국어 요약 1문단과 핵심 포인트 3~5개만 JSON으로 작성하세요. "
                    'JSON 형식은 {"summary": "...", "key_points": ["..."]} 입니다.',
                ),
                ("human", f"제목: {title}\n원문 URL: {url}\n\n본문:\n{article_text}"),
            ]
        )
        return parse_summary(_message_text(response.content))

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_chat_model,
            )
        return self._llm


def build_web_article_post_content(summary: str, key_points: list[str], url: str) -> str:
    point_lines = "\n".join(f"- {point}" for point in key_points)
    return (
        "## 한국어 요약\n\n"
        f"{summary}\n\n"
        "## 핵심 포인트\n\n"
        f"{point_lines}\n\n"
        "## 원문\n\n"
        f"- 원문: {url}\n\n"
        "#technews #webarticle"
    )


def parse_summary(content: str) -> ArticleSummary:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    payload = json.loads(text)
    summary = str(payload.get("summary", "")).strip()
    key_points = [str(point).strip() for point in payload.get("key_points", []) if str(point).strip()]
    if not summary or not key_points:
        raise ValueError("summary_generation_failed")
    return ArticleSummary(summary=summary, key_points=key_points[:5])


def source_id_for_url(url: str) -> str:
    normalized = normalize_url(url) or url.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def title_from_url(url: str) -> str:
    parsed = urlsplit(url)
    path = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    title = path.replace("-", " ").replace("_", " ").strip()
    return (title or parsed.netloc or "Web article")[:200]


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return str(content)


_news_curation_service: NewsCurationService | None = None


def get_news_curation_service() -> NewsCurationService:
    global _news_curation_service
    if _news_curation_service is None:
        _news_curation_service = NewsCurationService()
    return _news_curation_service
