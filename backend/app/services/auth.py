from random import SystemRandom

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import users as user_repository
from app.schemas.user import UserCreate, UserLogin

random = SystemRandom()


def generate_unique_nickname(db: Session) -> str:
    for _ in range(10000):
        nickname = f"익명{random.randint(0, 9999):04d}"
        if not user_repository.nickname_exists(db, nickname):
            return nickname
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not generate unique nickname",
    )


def register_user(db: Session, payload: UserCreate) -> User:
    email = str(payload.email)
    if user_repository.email_exists(db, email):
        raise HTTPException(status_code=409, detail="Email already registered")

    nickname = payload.nickname or generate_unique_nickname(db)
    if user_repository.nickname_exists(db, nickname):
        raise HTTPException(status_code=409, detail="Nickname already registered")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        nickname=nickname,
    )
    user_repository.add_user(db, user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if user_repository.email_exists(db, email):
            raise HTTPException(status_code=409, detail="Email already registered")
        if user_repository.nickname_exists(db, nickname):
            raise HTTPException(status_code=409, detail="Nickname already registered")
        raise HTTPException(status_code=409, detail="Could not register user")
    db.refresh(user)
    return user


def authenticate_user(db: Session, payload: UserLogin) -> User:
    user = user_repository.get_user_by_email(db, str(payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user
