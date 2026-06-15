import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.services.tags import TAG_NAME_PATTERN, normalize_tag_names
from app.schemas.tag import TagRead
from app.schemas.user import UserRead

tag_name_re = re.compile(TAG_NAME_PATTERN)


class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        tags = normalize_tag_names(value)
        invalid_tags = [tag for tag in tags if not tag_name_re.fullmatch(tag)]
        if invalid_tags:
            raise ValueError("Tags may only contain letters, numbers, Korean characters, and underscores.")
        return tags


class PostCreate(PostBase):
    pass


class PostUpdate(PostBase):
    pass


class PostRead(BaseModel):
    id: int
    title: str
    content: str
    author: UserRead
    tags: list[TagRead]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PostListItem(BaseModel):
    id: int
    title: str
    author: UserRead
    tags: list[TagRead]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PostPage(BaseModel):
    items: list[PostListItem]
    total: int
    page: int
    size: int
