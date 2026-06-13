from random import SystemRandom

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AUTH_COOKIE_NAME, get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
random = SystemRandom()


def generate_unique_nickname(db: Session) -> str:
    for _ in range(10000):
        nickname = f"익명{random.randint(0, 9999):04d}"
        exists = db.scalar(select(User.id).where(User.nickname == nickname))
        if exists is None:
            return nickname
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not generate unique nickname",
    )


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
    email = str(payload.email)
    email_exists = db.scalar(select(User.id).where(User.email == email))
    if email_exists is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    nickname = payload.nickname or generate_unique_nickname(db)
    nickname_exists = db.scalar(select(User.id).where(User.nickname == nickname))
    if nickname_exists is not None:
        raise HTTPException(status_code=409, detail="Nickname already registered")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        nickname=nickname,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(status_code=409, detail="Email already registered")
        if db.scalar(select(User.id).where(User.nickname == nickname)) is not None:
            raise HTTPException(status_code=409, detail="Nickname already registered")
        raise HTTPException(status_code=409, detail="Could not register user")
    db.refresh(user)
    return user


@router.post("/login", response_model=UserRead)
def login(
    payload: UserLogin,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    set_auth_cookie(response, create_access_token(str(user.id)))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
