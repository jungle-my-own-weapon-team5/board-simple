from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def email_exists(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None


def nickname_exists(db: Session, nickname: str) -> bool:
    return db.scalar(select(User.id).where(User.nickname == nickname)) is not None


def create_user(
    db: Session,
    *,
    email: str,
    password_hash: str,
    nickname: str,
) -> User:
    user = User(email=email, password_hash=password_hash, nickname=nickname)
    db.add(user)
    db.flush()
    return user
