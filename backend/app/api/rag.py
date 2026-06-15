from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.rag import RagAskRequest, RagAskResponse, RagSource
from app.services.rag import RagService, RagUnavailableError, get_rag_service

router = APIRouter(prefix="/rag", tags=["rag"])


def get_rag_service_dependency() -> RagService:
    return get_rag_service()


@router.post("/ask", response_model=RagAskResponse)
def ask_rag(
    payload: RagAskRequest,
    db: Session = Depends(get_db),
    rag_service: RagService = Depends(get_rag_service_dependency),
) -> RagAskResponse:
    try:
        result = rag_service.ask(db, payload.question)
    except RagUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return RagAskResponse(
        answer=result.answer,
        sources=[
            RagSource(
                post_id=source.post_id,
                title=source.title,
                excerpt=source.excerpt,
                score=source.score,
            )
            for source in result.sources
        ],
    )
