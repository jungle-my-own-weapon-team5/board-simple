from pydantic import BaseModel, Field


class RagChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class RagSource(BaseModel):
    post_id: int
    title: str
    heading: str | None = None
    anchor: str | None = None
    snippet: str


class RagChatResponse(BaseModel):
    answer: str
    sources: list[RagSource]
