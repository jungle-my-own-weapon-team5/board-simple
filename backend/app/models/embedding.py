"""Embedding profile과 chunk별 vector를 저장하는 ORM 모델입니다."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.core.database import Base


class Vector(UserDefinedType):
    """pgvector의 vector 컬럼을 SQLAlchemy에서 표현하는 최소 타입입니다.

    dimensions가 None이면 여러 profile 차원을 저장할 수 있는 일반 `vector`
    컬럼으로 생성합니다. 실제 dimension 검증은 embedding profile과 service가
    담당합니다.
    """

    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        if self.dimensions is None:
            return "vector"
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: object):
        def process(value: list[float] | tuple[float, ...] | str | None) -> str | None:
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(self, dialect: object, coltype: object):
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            if isinstance(value, tuple):
                return [float(item) for item in value]
            if isinstance(value, str):
                return _parse_vector_text(value)
            return value

        return process


def _parse_vector_text(value: str) -> list[float]:
    stripped_value = value.strip()
    if not stripped_value:
        return []
    try:
        parsed = json.loads(stripped_value)
    except json.JSONDecodeError:
        parsed = stripped_value.strip("[]").split(",")
    return [float(item) for item in parsed if str(item).strip()]


class EmbeddingProfile(Base):
    """하나의 embedding 검색 공간을 정의하는 provider/model/dimension 조합입니다."""

    __tablename__ = "embedding_profiles"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "model_name",
            "dimensions",
            "distance_metric",
            name="uq_embedding_profiles_provider_model_dimensions_metric",
        ),
        CheckConstraint("dimensions > 0", name="ck_embedding_profiles_dimensions_positive"),
        Index("ix_embedding_profiles_status_default", "status", "is_default"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(150))
    dimensions: Mapped[int] = mapped_column()
    distance_metric: Mapped[str] = mapped_column(String(30), default="cosine")
    vector_type: Mapped[str] = mapped_column(String(30), default="vector")
    status: Mapped[str] = mapped_column(String(30), default="active")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 같은 profile은 여러 chunk embedding row에서 참조됩니다.
    chunk_embeddings = relationship(
        "LegalDocumentChunkEmbedding",
        back_populates="embedding_profile",
    )
    # 실행 이력은 당시 사용한 profile을 추적합니다.
    rag_runs = relationship("RagRun", back_populates="embedding_profile")
    retrievals = relationship("RagRetrieval", back_populates="embedding_profile")


class LegalDocumentChunkEmbedding(Base):
    """chunk 하나에 대한 profile별 embedding vector와 처리 상태입니다."""

    __tablename__ = "legal_document_chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "embedding_profile_id",
            name="uq_chunk_embeddings_chunk_profile",
        ),
        Index(
            "ix_chunk_embeddings_profile_status",
            "embedding_profile_id",
            "embedding_status",
        ),
        Index("ix_chunk_embeddings_chunk_id", "chunk_id"),
        Index("ix_chunk_embeddings_content_checksum", "content_checksum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("legal_document_chunks.id", ondelete="CASCADE")
    )
    embedding_profile_id: Mapped[int] = mapped_column(
        ForeignKey("embedding_profiles.id", ondelete="RESTRICT")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    embedding_status: Mapped[str] = mapped_column(String(30), default="pending")
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_error: Mapped[str | None] = mapped_column(Text)
    content_checksum: Mapped[str] = mapped_column(String(128))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunk = relationship("LegalDocumentChunk", back_populates="embeddings")
    embedding_profile = relationship(
        "EmbeddingProfile",
        back_populates="chunk_embeddings",
    )
    retrievals = relationship("RagRetrieval", back_populates="chunk_embedding")
