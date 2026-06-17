from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.ai import (
    AgentStep,
    AgentChatRequest,
    EditorAgentRequest,
    EditorAgentResponse,
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
from app.services.editor_agent import run_editor_agent
from app.services.ai_runtime import run_agent, run_rag_quality_agent, search_external, search_rag
from app.services.discussion_topics import get_public_discussion_topics

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/topics", response_model=list[DiscussionTopic])
def list_discussion_topics(
    topic_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[DiscussionTopic]:
    return get_public_discussion_topics(db, settings, topic_date)


@router.post("/writing-assist", response_model=WritingAssistResponse)
def writing_assist(
    payload: WritingAssistRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WritingAssistResponse:
    editor_response = run_editor_agent(
        db,
        settings,
        payload.title,
        payload.content,
        payload.post_type,
        "",
        _legacy_writing_assist_message(payload),
        [],
    )
    return WritingAssistResponse(
        improved_titles=[editor_response.suggested_title] if editor_response.suggested_title else [],
        suggested_content=editor_response.suggested_content or editor_response.agent_message,
        tags=editor_response.tags,
        category=editor_response.category or "오늘의 떡밥",
        questions=editor_response.questions,
        keywords=editor_response.tags,
        agent_steps=[
            AgentStep(
                name="writing_assist.deprecated",
                output="구형 writing-assist 요청을 에디터 Agent로 위임했습니다.",
            ),
            *editor_response.agent_steps,
        ],
        evidence_summary=editor_response.evidence_summary,
        weak_evidence=editor_response.weak_evidence,
    )


def _legacy_writing_assist_message(payload: WritingAssistRequest) -> str:
    instruction = payload.instruction or "현재 초안을 바탕으로 글쓰기 추천을 만들어줘."
    return (
        f"{instruction}\n"
        "제목 후보, 본문 초안, 추천 태그, 카테고리, 토론 질문을 제안해줘. "
        "본문 작성이나 수정이 필요하면 suggested_content에 바로 적용 가능한 초안을 넣어줘."
    )


@router.post("/editor-agent/run", response_model=EditorAgentResponse)
def editor_agent_run(
    payload: EditorAgentRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> EditorAgentResponse:
    return run_editor_agent(
        db,
        settings,
        payload.title,
        payload.content,
        payload.post_type,
        payload.category,
        payload.message,
        payload.history,
    )


@router.post("/rag/search", response_model=RagSearchResponse)
def rag_search(
    payload: RagSearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RagSearchResponse:
    return search_rag(db, settings, payload.query, payload.top_k, payload.corpus)


@router.post("/rag/agent-search", response_model=RagQualityAgentResponse)
def rag_agent_search(
    payload: RagQualityAgentRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RagQualityAgentResponse:
    return run_rag_quality_agent(db, settings, payload.query, payload.top_k, payload.corpus)


@router.post("/external/search", response_model=ExternalSearchResponse)
def external_search(
    payload: ExternalSearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExternalSearchResponse:
    return search_external(db, payload.keyword, settings)


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
