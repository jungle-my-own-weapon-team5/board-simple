from datetime import date

from pydantic import BaseModel, Field


class ThumbnailPreviewRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    category: str = Field(default="왕과 권력", min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list)


class ThumbnailToolLog(BaseModel):
    tool: str
    input: str
    status: str
    elapsed_ms: int


class ThumbnailPreviewResponse(BaseModel):
    image_url: str | None
    visual_brief: str
    prompt: str
    agent_steps: list[str]
    tool_log: ThumbnailToolLog


class DiscussionTopicRefreshRequest(BaseModel):
    topic_date: date | None = None


class DiscussionTopicUpdate(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, min_length=1)
    question: str | None = Field(default=None, min_length=1)
    reason: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = Field(default=None, max_length=10)
    draft_title: str | None = Field(default=None, min_length=1, max_length=200)
    draft_content: str | None = Field(default=None, min_length=1)
    draft_post_type: str | None = Field(default=None, min_length=1, max_length=20)
    draft_category: str | None = Field(default=None, min_length=1, max_length=50)
    is_pinned: bool | None = None
    is_hidden: bool | None = None
