from typing import Any, Literal

from pydantic import BaseModel, Field

AgentActionName = Literal[
    "rag_search",
    "search_posts",
    "get_recent_posts",
    "get_post",
    "get_comments",
    "get_post_with_comments",
    "list_tags",
    "prepare_create_post",
    "prepare_post_draft",
    "plan_post_workflow",
    "answer_direct",
]


class AgentActionPlan(BaseModel):
    action: AgentActionName
    args: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = None
