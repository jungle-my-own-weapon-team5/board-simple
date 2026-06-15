from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tag import Tag


def list_tags(db: Session) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.name.asc())).all())


def get_tag_by_name(db: Session, name: str) -> Tag | None:
    return db.scalar(select(Tag).where(Tag.name == name))


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    for name in names:
        tag = get_tag_by_name(db, name)
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags
