from dataclasses import dataclass
from random import SystemRandom

from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories import users as user_repository
from app.schemas.user import UserCreate, UserLogin
from app.services.errors import AuthenticationError, ConflictError

random = SystemRandom()


@dataclass(frozen=True)
class LoginResult:
    user: User
    access_token: str


def generate_unique_nickname(db: Session) -> str:
    for _ in range(10000):
        nickname = f"익명{random.randint(0, 9999):04d}"
        if not user_repository.nickname_exists(db, nickname):
            return nickname
    raise ConflictError("Could not generate unique nickname")


def register_user(db: Session, payload: UserCreate) -> User:
    if user_repository.email_exists(db, str(payload.email)):
        raise ConflictError("Email already registered")

    nickname = payload.nickname or generate_unique_nickname(db)
    if user_repository.nickname_exists(db, nickname):
        raise ConflictError("Nickname already registered")

    user = user_repository.create_user(
        db,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        nickname=nickname,
    )
    db.commit()
    db.refresh(user)
    return user


def login_user(db: Session, payload: UserLogin) -> LoginResult:
    user = user_repository.get_user_by_email(db, str(payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Invalid email or password")

    return LoginResult(
        user=user,
        access_token=create_access_token(str(user.id)),
    )


def get_current_user_from_token(db: Session, access_token: str | None) -> User:
    if not access_token:
        raise AuthenticationError("Authentication required")

    subject = decode_access_token(access_token)
    if subject is None:
        raise AuthenticationError("Invalid authentication token")

    user = user_repository.get_user_by_id(db, int(subject)) if subject.isdigit() else None
    if user is None:
        raise AuthenticationError("User not found")
    return user
