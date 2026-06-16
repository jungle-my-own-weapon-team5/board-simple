from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AUTH_COOKIE_NAME, get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserRead
from app.services import auth as auth_service
from app.services.errors import AuthenticationError, ConflictError

router = APIRouter(prefix="/auth", tags=["auth"])


def set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    try:
        return auth_service.register_user(db, payload)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc


@router.post("/login", response_model=UserRead)
def login(
    payload: UserLogin,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    try:
        result = auth_service.login_user(db, payload)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=exc.detail) from exc

    set_auth_cookie(response, result.access_token)
    return result.user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
