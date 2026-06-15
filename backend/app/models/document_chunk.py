"""RAG 검색과 citation의 기본 단위인 문서 chunk ORM 모델입니다."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


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
    # embedding vector와 처리 상태는 profile별로 legal_document_chunk_embeddings에 저장합니다.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # chunk는 하나의 법률 문서에 속하며, citation과 retrieval의 기본 단위입니다.
    document = relationship("LegalDocument", back_populates="chunks")
    # 같은 chunk를 여러 provider/model/dimension profile로 임베딩할 수 있습니다.
    embeddings = relationship(
        "LegalDocumentChunkEmbedding",
        back_populates="chunk",
        cascade="all, delete-orphan",
    )
