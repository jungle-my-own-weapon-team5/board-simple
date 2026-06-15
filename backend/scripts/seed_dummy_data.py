from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.comment import Comment
from app.models.post import Post
from app.models.user import User
from app.services.tags import extract_tag_names, get_or_create_tags

DUMMY_PASSWORD = "password123"

USERS = [
    {"email": "sejo_fan@example.com", "nickname": "계유논객"},
    {"email": "sillok_reader@example.com", "nickname": "실록읽는밤"},
    {"email": "history_meme@example.com", "nickname": "조선밈장인"},
    {"email": "munjong_note@example.com", "nickname": "문종재평가단"},
    {"email": "hunmin_scholar@example.com", "nickname": "훈민정음탐정"},
]

POSTS = [
    {
        "email": "sejo_fan@example.com",
        "title": "세조의 왕위 찬탈, 조선 안정의 선택이었을까?",
        "post_type": "토론",
        "category": "왕과 권력",
        "view_count": 128,
        "content": (
            "계유정난을 보면 세조를 단순한 악역으로만 보기도 어렵고, 그렇다고 명분이 충분했다고 보기도 어려운 것 같습니다.\n\n"
            "결과적으로 조선 왕권이 안정됐다는 평가가 있다면, 그 결과가 단종 폐위를 정당화할 수 있을까요?\n\n"
            "#세조 #단종 #계유정난 #왕권"
        ),
    },
    {
        "email": "sillok_reader@example.com",
        "title": "실록에서 이상한 기록 발견함: 세종도 과로 문제 있었나?",
        "post_type": "발견",
        "category": "사료 발견",
        "view_count": 76,
        "content": (
            "세종 시기 기록을 읽다 보면 업무량이 너무 많았던 흔적이 자주 보입니다.\n\n"
            "요즘 기준으로 보면 과로 이슈처럼 읽히는 장면도 있는데, 이걸 현대식 노동 관점으로 봐도 될까요?\n\n"
            "#세종 #실록 #생활사"
        ),
    },
    {
        "email": "munjong_note@example.com",
        "title": "문종은 짧은 재위 때문에 과소평가된 왕일까?",
        "post_type": "질문",
        "category": "인물 열전",
        "view_count": 92,
        "content": (
            "문종은 항상 세종의 뒤를 이은 짧은 재위의 왕으로만 기억되는 느낌입니다.\n\n"
            "실제로는 제도 운영 능력이 꽤 있었다는 이야기도 있던데, 문종을 독립적인 군주로 다시 평가할 수 있을까요?\n\n"
            "#문종 #세종 #왕평가"
        ),
    },
    {
        "email": "hunmin_scholar@example.com",
        "title": "훈민정음 창제는 애민정신만으로 설명할 수 있을까?",
        "post_type": "사료 해석 요청",
        "category": "생활사와 문화",
        "view_count": 111,
        "content": (
            "훈민정음은 보통 애민정신으로 설명되지만, 행정과 지식 보급의 측면도 컸을 것 같습니다.\n\n"
            "문자 창제를 정치적 프로젝트로 보는 해석은 어디까지 설득력이 있을까요?\n\n"
            "#훈민정음 #세종 #문화"
        ),
    },
    {
        "email": "history_meme@example.com",
        "title": "광해군 재평가 논쟁, 드라마가 너무 많은 영향을 준 걸까?",
        "post_type": "가벼운 썰",
        "category": "오늘의 떡밥",
        "view_count": 64,
        "content": (
            "광해군 이야기는 사극이나 영화에서 볼 때마다 이미지가 꽤 달라지는 것 같습니다.\n\n"
            "실제 기록보다 대중문화가 재평가 분위기를 더 키운 부분도 있을까요?\n\n"
            "#광해군 #사극 #재평가"
        ),
    },
    {
        "email": "sillok_reader@example.com",
        "title": "붕당 정치는 그냥 당파 싸움이었을까, 공론 정치였을까?",
        "post_type": "토론",
        "category": "붕당과 정치",
        "view_count": 83,
        "content": (
            "붕당 정치를 배울 때는 늘 싸움처럼 느껴졌는데, 견제와 공론의 구조로 보는 해석도 있더라고요.\n\n"
            "어느 쪽으로 설명하는 게 더 균형 잡힌 관점일까요?\n\n"
            "#붕당 #정치 #사림"
        ),
    },
]

COMMENTS = [
    ("세조의 왕위 찬탈, 조선 안정의 선택이었을까?", "sillok_reader@example.com", "결과와 명분을 분리해서 봐야 할 것 같습니다."),
    ("세조의 왕위 찬탈, 조선 안정의 선택이었을까?", "history_meme@example.com", "댓글 싸움 나기 좋은 주제네요. 그래도 단종 쪽 명분이 너무 강해 보여요."),
    ("세조의 왕위 찬탈, 조선 안정의 선택이었을까?", "munjong_note@example.com", "문종이 오래 살았다면 이 구도가 완전히 달라졌을지도 궁금합니다."),
    ("실록에서 이상한 기록 발견함: 세종도 과로 문제 있었나?", "hunmin_scholar@example.com", "현대 개념을 바로 대입하긴 어렵지만 비교 관점은 재밌습니다."),
    ("문종은 짧은 재위 때문에 과소평가된 왕일까?", "sejo_fan@example.com", "문종 평가가 약한 건 재위 기간보다 사후 정치 구도가 더 큰 것 같아요."),
    ("훈민정음 창제는 애민정신만으로 설명할 수 있을까?", "sillok_reader@example.com", "행정 문서와 교육 확산까지 같이 보면 정치적 의미도 있다고 봅니다."),
    ("광해군 재평가 논쟁, 드라마가 너무 많은 영향을 준 걸까?", "sejo_fan@example.com", "대중문화 영향은 확실히 큰데, 기존 평가가 너무 단순했던 것도 있어요."),
    ("붕당 정치는 그냥 당파 싸움이었을까, 공론 정치였을까?", "hunmin_scholar@example.com", "초기 붕당과 후기 세도정치 이미지를 구분해야 할 듯합니다."),
]


def local_database_url() -> str:
    raw_url = os.environ.get("DATABASE_URL") or get_settings().database_url
    return raw_url.replace("@db:5432/", "@localhost:5432/")


def get_or_create_user(db: Session, email: str, nickname: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        return user

    user = User(
        email=email,
        nickname=nickname,
        password_hash=hash_password(DUMMY_PASSWORD),
    )
    db.add(user)
    db.flush()
    return user


def seed() -> None:
    database_url = local_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as db:
        users = {
            item["email"]: get_or_create_user(db, item["email"], item["nickname"])
            for item in USERS
        }

        posts_by_title: dict[str, Post] = {}
        for item in POSTS:
            post = db.scalar(select(Post).where(Post.title == item["title"]))
            if post is None:
                post = Post(
                    author_id=users[item["email"]].id,
                    title=item["title"],
                    content=item["content"],
                    post_type=item["post_type"],
                    category=item["category"],
                    view_count=item["view_count"],
                )
                post.tags = get_or_create_tags(db, extract_tag_names(item["content"]))
                db.add(post)
                db.flush()
            posts_by_title[item["title"]] = post

        for title, email, content in COMMENTS:
            post = posts_by_title[title]
            author = users[email]
            exists = db.scalar(
                select(Comment).where(
                    Comment.post_id == post.id,
                    Comment.author_id == author.id,
                    Comment.content == content,
                )
            )
            if exists is None:
                db.add(Comment(post_id=post.id, author_id=author.id, content=content))
                post.comment_count += 1

        db.commit()
        print(
            f"Seeded {len(USERS)} users, {len(POSTS)} posts, {len(COMMENTS)} comments."
        )
        print(f"Dummy user password: {DUMMY_PASSWORD}")


if __name__ == "__main__":
    seed()
