from pydantic import BaseModel, Field


class DiscussionTopic(BaseModel):
    source: str
    title: str
    summary: str
    question: str
    reason: str
    tags: list[str]


class WritingAssistRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = ""
    post_type: str = "토론"


class WritingAssistResponse(BaseModel):
    improved_titles: list[str]
    tags: list[str]
    category: str
    questions: list[str]
    keywords: list[str]


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=5)


class RagCitation(BaseModel):
    id: str
    title: str
    period: str
    summary: str
    relevance: float
    source_url: str


class RagSearchResponse(BaseModel):
    answer_summary: str
    citations: list[RagCitation]
    weak_evidence: bool


class RagQualityAgentRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=5)


class RagQualityAttempt(BaseModel):
    query: str
    citation_count: int
    max_relevance: float
    weak_evidence: bool
    decision: str


class AgentStep(BaseModel):
    name: str
    output: str


class RagQualityAgentResponse(BaseModel):
    final_query: str
    answer_summary: str
    citations: list[RagCitation]
    weak_evidence: bool
    attempts: list[RagQualityAttempt]
    agent_steps: list[AgentStep]
    needs_external_search: bool
    suggested_external_keywords: list[str]


class ExternalSearchRequest(BaseModel):
    keyword: str = Field(min_length=1)


class ExternalResource(BaseModel):
    title: str
    provider: str
    url: str
    description: str


class ToolLog(BaseModel):
    tool: str
    input: str
    status: str
    elapsed_ms: int


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
