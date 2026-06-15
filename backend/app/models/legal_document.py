"""정규화된 법률 문서와 중복/충돌 상태를 저장하는 ORM 모델입니다."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LegalDocument(Base):
    __tablename__ = "legal_documents"
    __table_args__ = (
        # 법령/판례 등 문서 유형과 날짜 기준 목록 조회에 사용합니다.
        Index("ix_legal_documents_document_type_published_date", "document_type", "published_date"),
        Index("ix_legal_documents_canonical_id", "canonical_id"),
        # 같은 canonical 문서라도 시행일 또는 버전이 다르면 별도 문서로 보존합니다.
        Index(
            "ix_legal_documents_type_canonical_effective",
            "document_type",
            "canonical_id",
            "effective_date",
        ),
        Index(
            "ix_legal_documents_type_canonical_version",
            "document_type",
            "canonical_id",
            "version_label",
        ),
        Index("ix_legal_documents_raw_checksum", "raw_checksum"),
        Index("ix_legal_documents_normalized_checksum", "normalized_checksum"),
        Index("ix_legal_documents_dedup_conflict", "dedup_status", "conflict_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("legal_sources.id", ondelete="CASCADE")
    )
    document_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    canonical_id: Mapped[str | None] = mapped_column(String(255))
    version_label: Mapped[str | None] = mapped_column(String(100))
    published_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    # raw_checksum은 수집 원문이 같은지 확인하고, normalized_checksum은 검색 본문 기준 중복을 판단합니다.
    raw_checksum: Mapped[str] = mapped_column(String(128))
    normalized_checksum: Mapped[str | None] = mapped_column(String(128))
    # 중복/충돌 상태는 모델이 직접 판단하지 않고 ingestion 서비스가 판정해 저장합니다.
    dedup_status: Mapped[str] = mapped_column(String(30), default="unique")
    conflict_status: Mapped[str] = mapped_column(String(30), default="none")
    # 중복 문서는 대표 문서를 가리키며, 대표 문서 삭제 시 연결만 해제합니다.
    duplicate_of_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("legal_documents.id", ondelete="SET NULL")
    )
    index_status: Mapped[str] = mapped_column(String(30), default="pending")
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source = relationship("LegalSource", back_populates="documents")
    # self-reference 관계입니다. 같은 문서로 판정된 경우 원본 문서 row를 추적합니다.
    duplicate_of = relationship(
        "LegalDocument",
        remote_side=[id],
        foreign_keys=[duplicate_of_document_id],
    )
    # chunk는 문서 본문에서 파생되므로 문서 삭제 시 함께 제거합니다.
    chunks = relationship(
        "LegalDocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )
