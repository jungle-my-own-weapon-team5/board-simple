from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models.post_rag_chunk import PostRagChunk


@dataclass(frozen=True)
class RagChunkSearchRow:
    """pgvector 검색 SQL 결과를 서비스 계층에 넘기기 위한 읽기 전용 행 객체입니다."""

    post_id: int
    title: str
    heading_path: str | None
    anchor: str | None
    content: str


def list_post_chunks(db: Session, post_id: int) -> list[PostRagChunk]:
    """게시글 하나에 저장된 RAG 청크를 chunk_index 순서로 조회합니다."""

    return list(
        db.scalars(
            select(PostRagChunk)
            .where(PostRagChunk.post_id == post_id)
            .order_by(PostRagChunk.chunk_index)
        ).all()
    )


def delete_post_chunks(db: Session, post_id: int) -> None:
    """게시글 하나에 연결된 기존 RAG 청크를 모두 삭제합니다."""

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
    """새 RAG 청크 레코드를 만들고 현재 세션에 추가합니다."""

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
    """현재 DB 연결이 pgvector 연산자를 사용할 수 있는 PostgreSQL인지 확인합니다."""

    return db.bind is not None and db.bind.dialect.name == "postgresql"


def search_chunks_by_embedding(
    db: Session,
    *,
    embedding: str,
    embedding_model: str,
    limit: int,
) -> list[RagChunkSearchRow]:
    """질문 임베딩과 가장 가까운 게시글 청크를 cosine distance 기준으로 조회합니다.

    `<=>`는 pgvector의 cosine distance 연산자입니다. 같은 임베딩 모델로 만든
    벡터끼리만 비교해야 차원과 의미 공간이 맞기 때문에 embedding_model로
    먼저 필터링합니다.
    """

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
