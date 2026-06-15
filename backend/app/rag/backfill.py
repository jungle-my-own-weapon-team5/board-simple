import argparse

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_session_local
from app.models.post import Post
from app.rag.service import index_post_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill RAG chunks for posts.")
    parser.add_argument("--all", action="store_true", help="Backfill every post.")
    parser.add_argument(
        "--post-id",
        action="append",
        type=int,
        default=[],
        help="Backfill a specific post id. Can be passed multiple times.",
    )
    args = parser.parse_args()

    if not args.all and not args.post_id:
        parser.error("Pass --all or at least one --post-id.")

    db = get_session_local()()
    try:
        statement = select(Post).options(selectinload(Post.tags))
        if not args.all:
            statement = statement.where(Post.id.in_(args.post_id))

        posts = db.scalars(statement.order_by(Post.id)).all()
        for post in posts:
            count = index_post_chunks(db, post)
            db.commit()
            print(f"post_id={post.id} chunks={count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
