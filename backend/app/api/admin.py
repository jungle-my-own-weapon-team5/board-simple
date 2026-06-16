from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.admin import ThumbnailPreviewRequest, ThumbnailPreviewResponse
from app.services.mcp_server import generate_thumbnail_for_post

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/thumbnail/preview", response_model=ThumbnailPreviewResponse)
def preview_thumbnail(
    payload: ThumbnailPreviewRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_admin_user),
) -> ThumbnailPreviewResponse:
    result = generate_thumbnail_for_post(
        db,
        settings,
        payload.title,
        payload.content,
        payload.category,
        payload.tags,
    )
    structured = result["structuredContent"]
    return ThumbnailPreviewResponse.model_validate(structured)
