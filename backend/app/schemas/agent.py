from typing import Literal

from pydantic import BaseModel, Field


class AgentPendingAction(BaseModel):
    type: Literal["create_post"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    confirm_action: AgentPendingAction | None = None


class AgentSource(BaseModel):
    post_id: int
    title: str
    heading: str | None = None
    anchor: str | None = None
    snippet: str


class AgentCreatedPost(BaseModel):
    post_id: int
    title: str


class AgentChatResponse(BaseModel):
    answer: str
    sources: list[AgentSource] = Field(default_factory=list)
    pending_action: AgentPendingAction | None = None
    created_post: AgentCreatedPost | None = None
