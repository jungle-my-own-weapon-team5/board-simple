from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    nickname: str | None = Field(default=None, min_length=2, max_length=32)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserPublicRead(BaseModel):
    id: int
    nickname: str

    model_config = {"from_attributes": True}


class UserRead(BaseModel):
    id: int
    email: EmailStr
    nickname: str
    created_at: datetime

    model_config = {"from_attributes": True}
