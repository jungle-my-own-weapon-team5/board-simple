from typing import Literal

from pydantic import BaseModel, Field


class AgentChatContext(BaseModel):
    page: Literal["new_post", "edit_post", "list", "detail", "unknown"] = "unknown"
    post_id: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    tags: list[str] = Field(default_factory=list)


class AgentPendingAction(BaseModel):
    type: Literal["create_post", "apply_post_draft"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    confirm_action: AgentPendingAction | None = None
    context: AgentChatContext | None = None


class AgentSource(BaseModel):
    post_id: int
    title: str
    heading: str | None = None
    anchor: str | None = None
    snippet: str


class AgentCreatedPost(BaseModel):
    post_id: int
    title: str


class AgentWorkflowStep(BaseModel):
    id: str
    label: str
    status: Literal["completed", "needs_confirmation", "pending"]
    detail: str | None = None


class AgentChatResponse(BaseModel):
    answer: str
    sources: list[AgentSource] = Field(default_factory=list)
    steps: list[AgentWorkflowStep] = Field(default_factory=list)
    pending_action: AgentPendingAction | None = None
    created_post: AgentCreatedPost | None = None
