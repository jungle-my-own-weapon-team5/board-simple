from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tag import Tag
from app.schemas.tag import TagRead

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagRead])
def list_tags(db: Session = Depends(get_db)) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.name.asc())).all())
