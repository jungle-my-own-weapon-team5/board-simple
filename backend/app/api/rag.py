from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.rag.service import RagGenerationError, RagNotConfiguredError, answer_question
from app.schemas.rag import RagChatRequest, RagChatResponse, RagSource

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/chat", response_model=RagChatResponse)
def chat_with_posts(
    payload: RagChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RagChatResponse:
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
