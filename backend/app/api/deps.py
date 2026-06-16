from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.schemas.user import UserRead

AUTH_COOKIE_NAME = "access_token"


def get_current_user(
    access_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    subject = decode_access_token(access_token)
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    user = db.get(User, int(subject)) if subject.isdigit() else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


def get_current_admin_user(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> User:
    if current_user.email != settings.admin_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def serialize_user(user: User, settings: Settings) -> UserRead:
    return UserRead.model_validate(user).model_copy(
        update={"is_admin": user.email == settings.admin_email}
    )
