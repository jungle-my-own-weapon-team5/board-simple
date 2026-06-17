"""FitLog image classification/RAG API boundary."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.fitlog_image_rag import ImageRagSearchResponse
from app.services.fitlog_image_rag import classify_and_route_image

router = APIRouter(prefix="/fitlog/image-rag", tags=["fitlog-image-rag"])


@router.post("/search", response_model=ImageRagSearchResponse)
async def search_image_rag(
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImageRagSearchResponse:
    _ = current_user
    image_bytes = await image.read()
    decision = classify_and_route_image(db, image_bytes)
    return ImageRagSearchResponse(
        query_handled=decision.query_handled,
        mode=decision.mode,
        action=decision.action,
        accepted_food_name=decision.accepted_food_name,
        training_candidate_required=decision.training_candidate_required,
        top_k=[asdict(candidate) for candidate in decision.candidates],
    )
