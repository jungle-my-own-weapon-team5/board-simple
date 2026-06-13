from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tag import Tag


def get_tag_by_name(db: Session, name: str) -> Tag | None:
    return db.scalar(select(Tag).where(Tag.name == name))


def list_tags(db: Session) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.name.asc())).all())


def add_tag(db: Session, tag: Tag) -> None:
    db.add(tag)
