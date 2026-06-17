import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tag import Tag

TAG_PATTERN = re.compile(r"#([0-9A-Za-z가-힣_]{1,50})")
TAG_NAME_PATTERN = re.compile(r"^[0-9A-Za-z가-힣_]{1,50}$")


def extract_tag_names(text: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for raw_name in TAG_PATTERN.findall(text):
        name = raw_name.strip().lower()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def normalize_tag_names(raw_names: list[str]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for raw_name in raw_names:
        name = raw_name.strip().lstrip("#").lower()
        if not name or name in seen or not TAG_NAME_PATTERN.match(name):
            continue
        seen.add(name)
        names.append(name)
    return names


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    for name in names:
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags
