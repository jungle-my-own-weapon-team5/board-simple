from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tag import TagRead
from app.schemas.user import UserRead


class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    post_type: str = Field(default="토론", min_length=1, max_length=20)
    category: str = Field(default="왕과 권력", min_length=1, max_length=50)


class PostCreate(PostBase):
    pass


class PostUpdate(PostBase):
    pass


class PostRead(BaseModel):
    id: int
    title: str
    content: str
    post_type: str
    category: str
    ai_search_summary: str | None
    thumbnail_url: str | None
    view_count: int
    comment_count: int
    has_ai_evidence: bool
    author: UserRead
    tags: list[TagRead]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PostListItem(BaseModel):
    id: int
    title: str
    post_type: str
    category: str
    ai_search_summary: str | None
    thumbnail_url: str | None
    view_count: int
    comment_count: int
    has_ai_evidence: bool
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
