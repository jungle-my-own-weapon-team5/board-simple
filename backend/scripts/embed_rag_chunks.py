from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select, func

from app.core.config import get_settings
from app.core.database import get_session_local
from app.models.ai import RagChunk, RagDocument
from app.services.ai_runtime import _embed_texts, _ensure_seed_documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate embeddings for RAG chunks.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="Maximum chunks to embed. 0 means all missing chunks.")
    parser.add_argument(
        "--reset-sillok",
        action="store_true",
        help="Delete existing Sillok RAG documents before syncing seed files.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not set. Add it to the root .env file first.")

    db = get_session_local()()
    try:
        if args.reset_sillok:
            deleted = db.query(RagDocument).filter(RagDocument.source_url.like("https://sillok.history.go.kr/id/%")).delete(
                synchronize_session=False
            )
            db.commit()
            print(f"reset_sillok_documents={deleted}")

        _ensure_seed_documents(db)
        total = db.scalar(select(func.count()).select_from(RagChunk)) or 0
        missing = db.scalar(
            select(func.count()).select_from(RagChunk).where(RagChunk.embedding_json.is_(None))
        ) or 0
        print(f"chunks={total} missing_embeddings={missing} model={settings.openai_embedding_model}")

        processed = 0
        started = time.perf_counter()
        while True:
            remaining_limit = args.limit - processed if args.limit else args.batch_size
            if args.limit and remaining_limit <= 0:
                break
            batch_size = min(args.batch_size, remaining_limit) if args.limit else args.batch_size
            chunks = db.scalars(
                select(RagChunk)
                .where(RagChunk.embedding_json.is_(None))
                .order_by(RagChunk.id)
                .limit(batch_size)
            ).all()
            if not chunks:
                break

            embeddings = _embed_texts(settings, [chunk.content for chunk in chunks])
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                chunk.embedding_json = json.dumps(embedding)
            db.commit()

            processed += len(chunks)
            elapsed = time.perf_counter() - started
            print(f"embedded={processed} last_chunk_id={chunks[-1].id} elapsed={elapsed:.1f}s")

        missing_after = db.scalar(
            select(func.count()).select_from(RagChunk).where(RagChunk.embedding_json.is_(None))
        ) or 0
        print(f"done processed={processed} missing_embeddings={missing_after}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
