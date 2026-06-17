from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select, func, text

from app.core.config import get_settings
from app.core.database import get_session_local
from app.models.ai import RagChunk, RagDocument
from app.services.ai_runtime import _embed_texts, _ensure_seed_documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate embeddings for RAG chunks.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="Maximum chunks to embed. 0 means all missing chunks.")
    parser.add_argument("--corpus", default=None, help="Embed only chunks whose document corpus matches this value.")
    parser.add_argument("--source-type", default=None, help="Embed only chunks whose document source_type matches this value.")
    parser.add_argument(
        "--reset-sillok",
        action="store_true",
        help="Delete existing Sillok RAG documents before syncing seed files.",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Sync seed Markdown into rag_documents/rag_chunks without generating embeddings.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.openai_api_key and not args.sync_only:
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
        backfilled = _backfill_pgvector_from_json(db, args.corpus, args.source_type)
        if backfilled:
            print(f"backfilled_pgvector={backfilled}")
        total = _count_chunks(db, args.corpus, args.source_type, missing_only=False)
        missing = _count_chunks(db, args.corpus, args.source_type, missing_only=True)
        print(f"chunks={total} missing_embeddings={missing} model={settings.openai_embedding_model}")
        if args.corpus:
            print(f"filter_corpus={args.corpus}")
        if args.source_type:
            print(f"filter_source_type={args.source_type}")
        if args.sync_only:
            print("sync_only=true embeddings_not_called=1")
            return

        processed = 0
        started = time.perf_counter()
        while True:
            remaining_limit = args.limit - processed if args.limit else args.batch_size
            if args.limit and remaining_limit <= 0:
                break
            batch_size = min(args.batch_size, remaining_limit) if args.limit else args.batch_size
            chunks = db.scalars(
                _select_missing_chunks(args.corpus, args.source_type).order_by(RagChunk.id).limit(batch_size)
            ).all()
            if not chunks:
                break

            embeddings = _embed_texts(settings, [chunk.content for chunk in chunks])
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                chunk.embedding_json = json.dumps(embedding)
                _set_pgvector_embedding(db, chunk.id, embedding)
            db.commit()

            processed += len(chunks)
            elapsed = time.perf_counter() - started
            print(f"embedded={processed} last_chunk_id={chunks[-1].id} elapsed={elapsed:.1f}s")

        missing_after = _count_chunks(db, args.corpus, args.source_type, missing_only=True)
        print(f"done processed={processed} missing_embeddings={missing_after}")
    finally:
        db.close()


def _count_chunks(db, corpus: str | None, source_type: str | None, missing_only: bool) -> int:
    statement = select(func.count(RagChunk.id))
    if corpus or source_type:
        statement = statement.join(RagDocument, RagChunk.document_id == RagDocument.id)
    statement = _apply_chunk_filters(statement, corpus, source_type)
    if missing_only:
        statement = statement.where(RagChunk.embedding_json.is_(None))
    return db.scalar(statement) or 0


def _select_missing_chunks(corpus: str | None, source_type: str | None):
    statement = select(RagChunk)
    if corpus or source_type:
        statement = statement.join(RagDocument, RagChunk.document_id == RagDocument.id)
    statement = _apply_chunk_filters(statement, corpus, source_type)
    return statement.where(RagChunk.embedding_json.is_(None))


def _apply_chunk_filters(statement, corpus: str | None, source_type: str | None):
    if corpus:
        statement = statement.where(RagDocument.corpus == corpus)
    if source_type:
        statement = statement.where(RagDocument.source_type == source_type)
    return statement


def _backfill_pgvector_from_json(db, corpus: str | None, source_type: str | None) -> int:
    if db.get_bind().dialect.name != "postgresql":
        return 0
    statement = select(RagChunk)
    if corpus or source_type:
        statement = statement.join(RagDocument, RagChunk.document_id == RagDocument.id)
    statement = _apply_chunk_filters(statement, corpus, source_type)
    chunks = db.scalars(
        statement
        .where(RagChunk.embedding_json.is_not(None))
        .where(text("rag_chunks.embedding IS NULL"))
    ).all()
    for chunk in chunks:
        _set_pgvector_embedding(db, chunk.id, json.loads(chunk.embedding_json or "[]"))
    if chunks:
        db.commit()
    return len(chunks)


def _set_pgvector_embedding(db, chunk_id: int, embedding: list[float]) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text("UPDATE rag_chunks SET embedding = (:embedding)::vector WHERE id = :chunk_id"),
        {"embedding": _pgvector_literal(embedding), "chunk_id": chunk_id},
    )


def _pgvector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.10g}" for value in values) + "]"


if __name__ == "__main__":
    main()
