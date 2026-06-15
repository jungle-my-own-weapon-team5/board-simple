"""법률 문서의 수집 출처를 표현하는 ORM 모델입니다."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, JSON, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LegalSource(Base):
    __tablename__ = "legal_sources"
    __table_args__ = (
        # 출처 provider와 문서 유형을 함께 조회하는 수집/동기화 작업에 사용합니다.
        Index("ix_legal_sources_provider_source_type", "provider", "source_type"),
        # external_id가 있는 외부 출처는 같은 provider 안에서 하나의 출처로 취급합니다.
        Index(
            "uq_legal_sources_provider_external_id",
            "provider",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(50))
    source_type: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 하나의 출처에서 여러 법률 문서 버전 또는 문서 유형이 파생될 수 있습니다.
    documents = relationship(
        "LegalDocument", back_populates="source", cascade="all, delete-orphan"
    )
