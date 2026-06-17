from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

RagCorpusMode = Literal["auto", "encykorea", "legacy", "sinpyeon_hanguksa", "sillok-v2", "all"]


class RagCitation(BaseModel):
    id: str
    title: str
    period: str
    summary: str
    relevance: float
    source_url: str


class DiscussionTopic(BaseModel):
    id: int | None = None
    topic_date: date | None = None
    source: str
    title: str
    summary: str
    question: str
    reason: str
    tags: list[str]
    draft_title: str | None = None
    draft_content: str | None = None
    draft_post_type: str = "토론"
    draft_category: str = "오늘의 떡밥"
    citations: list[RagCitation] = Field(default_factory=list)
    is_pinned: bool = False
    is_hidden: bool = False


class WritingAssistRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = ""
    post_type: str = "토론"
    instruction: str | None = Field(default=None, max_length=1000)


class AgentStep(BaseModel):
    name: str
    output: str


class ExternalResource(BaseModel):
    title: str
    provider: str
    url: str
    description: str
    source_type: str = ""
    result_type: str = ""
    verification_status: str = ""
    content_excerpt: str | None = None
    confidence: float = 0.0
    can_quote: bool = False


class ToolLog(BaseModel):
    tool: str
    input: str
    status: str
    elapsed_ms: int


class WritingAssistResponse(BaseModel):
    improved_titles: list[str]
    suggested_content: str | None = None
    tags: list[str]
    category: str
    questions: list[str]
    keywords: list[str]
    agent_steps: list[AgentStep] = Field(default_factory=list)
    evidence_summary: str | None = None
    weak_evidence: bool = False


class EditorAgentHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class EditorAgentRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = ""
    post_type: str = "토론"
    category: str = ""
    message: str = Field(min_length=1, max_length=2000)
    history: list[EditorAgentHistoryMessage] = Field(default_factory=list, max_length=12)


class EditorAgentResponse(BaseModel):
    action: str
    agent_message: str
    suggested_title: str | None = None
    suggested_content: str | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    questions: list[str] = Field(default_factory=list)
    external_resources: list[ExternalResource] = Field(default_factory=list)
    tool_logs: list[ToolLog] = Field(default_factory=list)
    agent_steps: list[AgentStep] = Field(default_factory=list)
    evidence_summary: str | None = None
    weak_evidence: bool = False


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=5)
    corpus: RagCorpusMode = "auto"


class RagSearchResponse(BaseModel):
    answer_summary: str
    citations: list[RagCitation]
    weak_evidence: bool
    searched_corpora: list[str] = Field(default_factory=list)


class RagQualityAgentRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=5)
    corpus: RagCorpusMode = "auto"


class RagQualityAttempt(BaseModel):
    query: str
    citation_count: int
    max_relevance: float
    weak_evidence: bool
    decision: str


class RagQualityAgentResponse(BaseModel):
    final_query: str
    answer_summary: str
    citations: list[RagCitation]
    weak_evidence: bool
    searched_corpora: list[str] = Field(default_factory=list)
    attempts: list[RagQualityAttempt]
    agent_steps: list[AgentStep]
    needs_external_search: bool
    suggested_external_keywords: list[str]


class ExternalSearchRequest(BaseModel):
    keyword: str = Field(min_length=1)


class ExternalSearchResponse(BaseModel):
    resources: list[ExternalResource]
    tool_log: ToolLog


class AgentRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    topic: str = Field(min_length=1)


class AgentChatPageContext(BaseModel):
    path: str | None = Field(default=None, max_length=200)
    post_id: int | None = None
    post_title: str | None = Field(default=None, max_length=200)
    post_summary: str | None = Field(default=None, max_length=1000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    page_context: AgentChatPageContext | None = None


class AgentRunResponse(BaseModel):
    steps: list[AgentStep]
    final_answer: str
    tool_logs: list[ToolLog]


class CommentSummaryRequest(BaseModel):
    comments: list[str]


class CommentSummaryResponse(BaseModel):
    main_points: list[str]
    disagreements: list[str]
    needs_evidence: list[str]
    next_questions: list[str]
