from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.user import UserPublicRead


class CommentCreate(BaseModel):
    content: str = Field(min_length=1)


class CommentUpdate(BaseModel):
    content: str = Field(min_length=1)


class CommentRead(BaseModel):
    id: int
    post_id: int
    content: str
    author: UserPublicRead
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentPage(BaseModel):
    items: list[CommentRead]
    total: int
    offset: int
    limit: int
