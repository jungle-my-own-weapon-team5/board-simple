from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.rag import RagChatRequest, RagChatResponse, RagSource
from app.services.rag import RagGenerationError, RagNotConfiguredError, answer_question

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/chat", response_model=RagChatResponse)
def chat_with_posts(
    payload: RagChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RagChatResponse:
    """로그인 사용자의 게시글 RAG 질문을 받아 답변과 출처를 반환합니다.

    인증은 current_user 의존성에서 강제됩니다. 이 함수는 API 예외 변환만
    담당하고, 실제 검색과 답변 생성 로직은 서비스 계층의 answer_question에
    위임합니다.
    """

    try:
        answer = answer_question(db, payload.message)
    except RagNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG is not configured.",
        ) from exc
    except RagGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="RAG answer generation failed.",
        ) from exc

    return RagChatResponse(
        answer=answer.answer,
        sources=[
            RagSource(
                post_id=source.post_id,
                title=source.title,
                heading=source.heading,
                anchor=source.anchor,
                snippet=source.snippet,
            )
            for source in answer.sources
        ],
    )
