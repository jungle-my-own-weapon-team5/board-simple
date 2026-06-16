from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.ai import (
    AgentChatRequest,
    AgentRunRequest,
    AgentRunResponse,
    CommentSummaryRequest,
    CommentSummaryResponse,
    DiscussionTopic,
    ExternalSearchRequest,
    ExternalSearchResponse,
    RagQualityAgentRequest,
    RagQualityAgentResponse,
    RagSearchRequest,
    RagSearchResponse,
    WritingAssistRequest,
    WritingAssistResponse,
)
from app.services.chat_agent import run_chat_agent
from app.services.ai_runtime import (
    get_discussion_topics,
    make_writing_assist,
    run_agent,
    run_rag_quality_agent,
    search_external,
    search_rag,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/topics", response_model=list[DiscussionTopic])
def list_discussion_topics() -> list[DiscussionTopic]:
    return get_discussion_topics()


@router.post("/writing-assist", response_model=WritingAssistResponse)
def writing_assist(
    payload: WritingAssistRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WritingAssistResponse:
    return make_writing_assist(db, settings, payload.title, payload.content, payload.post_type)


@router.post("/rag/search", response_model=RagSearchResponse)
def rag_search(
    payload: RagSearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RagSearchResponse:
    return search_rag(db, settings, payload.query, payload.top_k)


@router.post("/rag/agent-search", response_model=RagQualityAgentResponse)
def rag_agent_search(
    payload: RagQualityAgentRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RagQualityAgentResponse:
    return run_rag_quality_agent(db, settings, payload.query, payload.top_k)


@router.post("/external/search", response_model=ExternalSearchResponse)
def external_search(
    payload: ExternalSearchRequest,
    db: Session = Depends(get_db),
) -> ExternalSearchResponse:
    return search_external(db, payload.keyword)


@router.post("/agent/run", response_model=AgentRunResponse)
def agent_run(
    payload: AgentRunRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AgentRunResponse:
    return run_agent(db, settings, payload.goal, payload.topic)


@router.post("/agent/chat", response_model=AgentRunResponse)
def agent_chat(
    payload: AgentChatRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> AgentRunResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message must not be empty",
        )
    return run_chat_agent(db, settings, message, payload.page_context, current_user)


@router.post("/comments/summarize", response_model=CommentSummaryResponse)
def summarize_comments(payload: CommentSummaryRequest) -> CommentSummaryResponse:
    comments = [comment for comment in payload.comments if comment.strip()]
    if not comments:
        return CommentSummaryResponse(
            main_points=["아직 요약할 댓글이 없습니다."],
            disagreements=[],
            needs_evidence=[],
            next_questions=["첫 의견을 남겨 토론을 시작해보세요."],
        )
    return CommentSummaryResponse(
        main_points=[f"총 {len(comments)}개의 댓글에서 주제 해석과 평가 의견이 오갔습니다."],
        disagreements=["명분을 중시하는 관점과 결과를 중시하는 관점이 나뉩니다."],
        needs_evidence=["구체적인 사료 기록을 더 확인하면 토론이 선명해집니다."],
        next_questions=["당시 기준과 오늘날 기준을 분리해서 평가할 수 있을까요?"],
    )
