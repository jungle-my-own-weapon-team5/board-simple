import argparse

from app.core.database import get_session_local
from app.services.rag import backfill_post_chunks


def main() -> None:
    """CLI 인자를 읽어 기존 게시글의 RAG 청크를 일괄 생성합니다."""

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
        post_ids = None if args.all else args.post_id
        for post_id, count in backfill_post_chunks(db, post_ids=post_ids):
            print(f"post_id={post_id} chunks={count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
