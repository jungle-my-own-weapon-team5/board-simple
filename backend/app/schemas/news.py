from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


NewsSource = Literal["top", "best", "new", "search"]
SummaryStatus = Literal["success", "failed"]
DuplicateReason = Literal["same_url", "similar_title", "rag"]


class DuplicateMatch(BaseModel):
    post_id: int
    title: str
    reason: DuplicateReason
    score: float | None = None


class HackerNewsPreviewRequest(BaseModel):
    source: NewsSource
    query: str | None = None
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @model_validator(mode="after")
    def require_search_query(self) -> "HackerNewsPreviewRequest":
        if self.source == "search" and not self.query:
            raise ValueError("query is required for search")
        return self


class HackerNewsPreviewItem(BaseModel):
    hn_id: int
    title: str
    url: str | None = None
    hn_url: str
    author: str | None = None
    points: int | None = None
    comment_count: int | None = None
    created_at: datetime | None = None
    summary_status: SummaryStatus
    summary: str | None = None
    key_points: list[str] = []
    duplicate_matches: list[DuplicateMatch] = Field(default_factory=list)
    is_imported: bool
    error: str | None = None


class HackerNewsPreviewResponse(BaseModel):
    items: list[HackerNewsPreviewItem]


class HackerNewsImportItem(BaseModel):
    hn_id: int
    title: str = Field(min_length=1, max_length=500)
    url: str | None = None
    hn_url: str = Field(min_length=1, max_length=2048)
    summary: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)

    @field_validator("title", "summary", "hn_url")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("url")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("key_points")
    @classmethod
    def strip_key_points(cls, value: list[str]) -> list[str]:
        points = [point.strip() for point in value if point.strip()]
        if not points:
            raise ValueError("key_points must contain at least one item")
        return points


class HackerNewsImportRequest(BaseModel):
    items: list[HackerNewsImportItem] = Field(min_length=1, max_length=20)


class HackerNewsCreatedPost(BaseModel):
    post_id: int
    hn_id: int
    title: str


class HackerNewsSkippedItem(BaseModel):
    hn_id: int
    reason: str


class HackerNewsImportResponse(BaseModel):
    created: list[HackerNewsCreatedPost]
    skipped: list[HackerNewsSkippedItem]


class WebArticlePreviewRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    article_text: str | None = None

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("url must not be blank")
        return stripped

    @field_validator("article_text")
    @classmethod
    def strip_article_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WebArticlePreviewItem(BaseModel):
    source_type: Literal["web_article"] = "web_article"
    source_id: str
    title: str
    url: str
    summary_status: SummaryStatus
    summary: str | None = None
    key_points: list[str] = Field(default_factory=list)
    duplicate_matches: list[DuplicateMatch] = Field(default_factory=list)
    error: str | None = None


class WebArticlePreviewResponse(BaseModel):
    item: WebArticlePreviewItem


class WebArticleImportItem(BaseModel):
    source_type: Literal["web_article"] = "web_article"
    source_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    summary: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)

    @field_validator("source_id", "title", "url", "summary")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("key_points")
    @classmethod
    def strip_key_points(cls, value: list[str]) -> list[str]:
        points = [point.strip() for point in value if point.strip()]
        if not points:
            raise ValueError("key_points must contain at least one item")
        return points


class WebArticleImportRequest(BaseModel):
    items: list[WebArticleImportItem] = Field(min_length=1, max_length=20)


class WebArticleCreatedPost(BaseModel):
    post_id: int
    source_id: str
    title: str


class WebArticleSkippedItem(BaseModel):
    source_id: str
    reason: str


class WebArticleImportResponse(BaseModel):
    created: list[WebArticleCreatedPost]
    skipped: list[WebArticleSkippedItem]
