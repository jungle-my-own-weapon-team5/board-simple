from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tag import Tag

TAG_NAME_PATTERN = r"^[0-9A-Za-z가-힣_]{1,50}$"


def normalize_tag_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized_names: list[str] = []
    for raw_name in names:
        name = raw_name.strip().removeprefix("#").lower()
        if name and name not in seen:
            seen.add(name)
            normalized_names.append(name)
    return normalized_names


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    for name in normalize_tag_names(names):
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags
