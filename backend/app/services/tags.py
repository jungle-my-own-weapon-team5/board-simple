import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.tag import Tag
from app.repositories import tags as tag_repository

TAG_PATTERN = re.compile(r"#([0-9A-Za-z가-힣_]{1,50})")


def extract_tag_names(text: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for raw_name in TAG_PATTERN.findall(text):
        name = raw_name.strip().lower()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    for name in names:
        tag = tag_repository.get_tag_by_name(db, name)
        if tag is None:
            try:
                with db.begin_nested():
                    tag = Tag(name=name)
                    tag_repository.add_tag(db, tag)
                    db.flush()
            except IntegrityError:
                tag = tag_repository.get_tag_by_name(db, name)
                if tag is None:
                    raise
        tags.append(tag)
    return tags


def list_tags(db: Session) -> list[Tag]:
    return tag_repository.list_tags(db)
