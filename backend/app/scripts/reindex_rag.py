from sqlalchemy import select

from app.core.database import get_session_local
from app.models.post import Post
from app.services.rag import RagUnavailableError, get_rag_service


def main() -> None:
    rag_service = get_rag_service()
    try:
        rag_service.require_configured()
    except RagUnavailableError as exc:
        raise SystemExit(f"RAG reindex is not available: {exc}") from exc

    SessionLocal = get_session_local()
    with SessionLocal() as db:
        posts = db.scalars(select(Post).order_by(Post.id)).all()
        for post in posts:
            rag_service.index_post(db, post)
    print(f"Reindexed {len(posts)} posts for RAG.")


if __name__ == "__main__":
    main()
