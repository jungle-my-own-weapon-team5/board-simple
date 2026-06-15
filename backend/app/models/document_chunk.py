"""RAG 검색 단위인 문서 chunk와 embedding 상태를 저장하는 ORM 모델입니다."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.core.database import Base


class Vector(UserDefinedType):
    """pgvector의 vector(N) 컬럼을 SQLAlchemy에서 표현하기 위한 최소 타입입니다."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"


class LegalDocumentChunk(Base):
    __tablename__ = "legal_document_chunks"
    __table_args__ = (
        # 같은 문서 안에서 chunk_index는 원문 순서를 나타내므로 중복될 수 없습니다.
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_legal_document_chunks_document_id_chunk_index",
        ),
        Index("ix_legal_document_chunks_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("legal_documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column()
    heading: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column()
    # embedding은 생성 전에는 비어 있을 수 있고, embedding_status가 처리 상태를 나타냅니다.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_status: Mapped[str] = mapped_column(String(30), default="pending")
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # chunk는 하나의 법률 문서에 속하며, citation과 retrieval의 기본 단위입니다.
    document = relationship("LegalDocument", back_populates="chunks")
