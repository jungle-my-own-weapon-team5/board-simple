from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tag import TagRead
from app.schemas.user import UserRead


class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class PostCreate(PostBase):
    pass


class PostUpdate(PostBase):
    pass


class RelatedPost(BaseModel):
    post_id: int
    title: str
    score: float | None = None


class PostRead(BaseModel):
    id: int
    title: str
    content: str
    author: UserRead
    tags: list[TagRead]
    created_at: datetime
    updated_at: datetime
    related_posts: list[RelatedPost] = Field(default_factory=list)

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
