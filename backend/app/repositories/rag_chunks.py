from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models.post_rag_chunk import PostRagChunk


@dataclass(frozen=True)
class RagChunkSearchRow:
    post_id: int
    title: str
    heading_path: str | None
    anchor: str | None
    content: str


def list_post_chunks(db: Session, post_id: int) -> list[PostRagChunk]:
    return list(
        db.scalars(
            select(PostRagChunk)
            .where(PostRagChunk.post_id == post_id)
            .order_by(PostRagChunk.chunk_index)
        ).all()
    )


def delete_post_chunks(db: Session, post_id: int) -> None:
    db.execute(delete(PostRagChunk).where(PostRagChunk.post_id == post_id))
    db.flush()


def create_post_chunk(
    db: Session,
    *,
    post_id: int,
    chunk_index: int,
    heading_path: str | None,
    anchor: str | None,
    content: str,
    content_hash: str,
    embedding_model: str,
    embedding: list[float],
) -> PostRagChunk:
    chunk = PostRagChunk(
        post_id=post_id,
        chunk_index=chunk_index,
        heading_path=heading_path,
        anchor=anchor,
        content=content,
        content_hash=content_hash,
        embedding_model=embedding_model,
        embedding=embedding,
    )
    db.add(chunk)
    db.flush()
    return chunk


def supports_vector_search(db: Session) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def search_chunks_by_embedding(
    db: Session,
    *,
    embedding: str,
    embedding_model: str,
    limit: int,
) -> list[RagChunkSearchRow]:
    rows = db.execute(
        text(
            """
            SELECT
                chunks.post_id,
                posts.title,
                chunks.heading_path,
                chunks.anchor,
                chunks.content
            FROM post_rag_chunks AS chunks
            JOIN posts ON posts.id = chunks.post_id
            WHERE chunks.embedding_model = :embedding_model
            ORDER BY chunks.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {
            "embedding": embedding,
            "embedding_model": embedding_model,
            "limit": limit,
        },
    ).mappings()

    return [
        RagChunkSearchRow(
            post_id=row["post_id"],
            title=row["title"],
            heading_path=row["heading_path"],
            anchor=row["anchor"],
            content=row["content"],
        )
        for row in rows
    ]
