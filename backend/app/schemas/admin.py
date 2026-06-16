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
