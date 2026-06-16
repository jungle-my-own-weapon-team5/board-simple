from pydantic import BaseModel, Field


class RagChatRequest(BaseModel):
    """프론트에서 RAG 챗봇에 보낼 사용자 질문 요청입니다."""

    message: str = Field(min_length=1, max_length=1000)


class RagSource(BaseModel):
    """RAG 답변에 함께 표시할 게시글 출처 정보입니다."""

    post_id: int
    title: str
    heading: str | None = None
    anchor: str | None = None
    snippet: str


class RagChatResponse(BaseModel):
    """RAG 챗봇 답변 본문과 출처 목록을 담은 응답입니다."""

    answer: str
    sources: list[RagSource]
