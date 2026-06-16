from datetime import datetime

from pydantic import BaseModel


class McpUser(BaseModel):
    id: int
    email: str
    nickname: str
    created_at: datetime


class McpTag(BaseModel):
    id: int
    name: str


class McpPostListItem(BaseModel):
    id: int
    title: str
    author: McpUser
    tags: list[McpTag]
    created_at: datetime
    updated_at: datetime


class McpPostDetail(McpPostListItem):
    content: str


class McpPostPage(BaseModel):
    items: list[McpPostListItem]
    total: int
    page: int
    size: int


class McpComment(BaseModel):
    id: int
    post_id: int
    content: str
    author: McpUser
    created_at: datetime
    updated_at: datetime


class McpCommentPage(BaseModel):
    items: list[McpComment]
    total: int
    offset: int
    limit: int


class McpPostWithComments(BaseModel):
    post: McpPostDetail
    comments: McpCommentPage
