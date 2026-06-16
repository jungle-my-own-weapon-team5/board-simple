from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.core.database import Base

EMBEDDING_DIMENSIONS = 1536


class EmbeddingVector(TypeDecorator):
    """환경별로 RAG 임베딩 컬럼 타입을 선택하는 SQLAlchemy 타입입니다.

    운영 PostgreSQL에서는 pgvector의 Vector(1536)을 사용해 유사도 검색을
    지원하고, 테스트용 SQLite 등에서는 JSON으로 저장해 모델 생성이 가능하게
    합니다.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        """DB dialect에 맞는 실제 컬럼 타입을 SQLAlchemy에 알려줍니다."""

        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(EMBEDDING_DIMENSIONS))
        return dialect.type_descriptor(JSON())


class PostRagChunk(Base):
    """게시글 본문을 검색 가능한 단위로 나눈 RAG 청크 테이블 모델입니다."""

    __tablename__ = "post_rag_chunks"
    __table_args__ = (
        UniqueConstraint("post_id", "chunk_index", name="uq_post_rag_chunks_post_id_chunk_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    anchor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(100), index=True)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    post = relationship("Post", back_populates="rag_chunks")
