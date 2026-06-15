from collections.abc import Generator
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import LegalDocument, LegalDocumentChunk, LegalSource
from app.repositories import document_chunks
from app.services.rag.ingestion import (
    IngestLegalDocumentInput,
    ingest_legal_document,
)
from app.services.rag.normalization import calculate_text_checksum, normalize_text


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_ingest_legal_document_persists_source_document_and_chunks(
    db: Session,
) -> None:
    raw_text = """
      제1조(목적)
      이 법은 테스트 목적을 정한다.

      제2조(정의)
      이 법에서 사용하는 용어의 뜻은 다음과 같다.
    """

    result = ingest_legal_document(
        db,
        IngestLegalDocumentInput(
            provider="FIXTURE",
            source_type="STATUTE",
            document_type="STATUTE",
            title="  테스트 법률  ",
            raw_text=raw_text,
            canonical_id="LAW-001",
            version_label="2026-01-01",
            published_date=date(2025, 12, 1),
            effective_date=date(2026, 1, 1),
            source_url="https://example.test/law-001",
            external_id="law-001",
            metadata_json={"fixture": "statute"},
        ),
    )

    assert result.source.id is not None
    assert result.source.provider == "fixture"
    assert result.source.source_type == "statute"
    assert result.source.metadata_json == {"fixture": "statute"}
    assert result.document.id is not None
    assert result.document.title == "테스트 법률"
    assert result.document.raw_text == raw_text
    assert result.document.normalized_text == normalize_text(raw_text)
    assert result.document.raw_checksum == calculate_text_checksum(raw_text)
    assert result.document.normalized_checksum == calculate_text_checksum(
        normalize_text(raw_text)
    )
    assert result.document.dedup_status == "unique"
    assert result.document.conflict_status == "none"
    assert result.document.duplicate_of_document_id is None
    assert result.document.index_status == "pending"

    chunks = document_chunks.list_chunks_by_document(db, result.document.id)
    assert len(chunks) == 2
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert chunks[0].heading == "제1조(목적)"
    assert chunks[0].embedding_status == "pending"
    assert chunks[0].metadata_json["document_type"] == "statute"
    assert chunks[0].metadata_json["canonical_id"] == "LAW-001"
    assert chunks[0].metadata_json["effective_date"] == "2026-01-01"


def test_ingest_legal_document_marks_same_version_same_normalized_text_as_duplicate(
    db: Session,
) -> None:
    first = ingest_legal_document(
        db,
        _statute_input(
            raw_text="제1조(목적)\n이 법은 테스트 목적을 정한다.",
            external_id="law-duplicate-source",
        ),
    )
    second = ingest_legal_document(
        db,
        _statute_input(
            raw_text="  제1조(목적)\r\n이 법은   테스트 목적을 정한다.  ",
            external_id="law-duplicate-source",
        ),
    )

    assert second.source.id == first.source.id
    assert second.document.dedup_status == "duplicate"
    assert second.document.conflict_status == "none"
    assert second.document.duplicate_of_document_id == first.document.id
    assert second.duplicate_of_document_id == first.document.id
    assert second.is_duplicate is True
    assert second.needs_conflict_review is False
    assert second.document.raw_checksum != first.document.raw_checksum
    assert second.document.normalized_checksum == first.document.normalized_checksum


def test_ingest_legal_document_marks_same_version_different_text_as_conflict(
    db: Session,
) -> None:
    first = ingest_legal_document(
        db,
        _statute_input(raw_text="제1조(목적)\n기존 본문입니다."),
    )
    second = ingest_legal_document(
        db,
        _statute_input(raw_text="제1조(목적)\n수정된 본문입니다."),
    )

    assert second.document.dedup_status == "unique"
    assert second.document.conflict_status == "review_required"
    assert second.document.duplicate_of_document_id is None
    assert second.conflicting_document_ids == [first.document.id]
    assert second.is_duplicate is False
    assert second.needs_conflict_review is True


def test_ingest_legal_document_keeps_different_effective_date_as_unique_version(
    db: Session,
) -> None:
    first = ingest_legal_document(
        db,
        _statute_input(
            raw_text="제1조(목적)\n같은 본문입니다.",
            version_label="2026-01-01",
            effective_date=date(2026, 1, 1),
        ),
    )
    second = ingest_legal_document(
        db,
        _statute_input(
            raw_text="제1조(목적)\n같은 본문입니다.",
            version_label="2026-02-01",
            effective_date=date(2026, 2, 1),
        ),
    )

    assert second.document.normalized_checksum == first.document.normalized_checksum
    assert second.document.dedup_status == "unique"
    assert second.document.conflict_status == "none"
    assert second.document.duplicate_of_document_id is None


def test_ingest_legal_document_rejects_blank_required_values(db: Session) -> None:
    with pytest.raises(ValueError, match="raw_text must not be blank"):
        ingest_legal_document(
            db,
            _statute_input(raw_text=" \n\t "),
        )

    assert db.query(LegalSource).count() == 0
    assert db.query(LegalDocument).count() == 0
    assert db.query(LegalDocumentChunk).count() == 0


def _statute_input(
    *,
    raw_text: str,
    external_id: str = "law-001",
    version_label: str = "2026-01-01",
    effective_date: date = date(2026, 1, 1),
) -> IngestLegalDocumentInput:
    return IngestLegalDocumentInput(
        provider="fixture",
        source_type="statute",
        document_type="statute",
        title="테스트 법률",
        raw_text=raw_text,
        canonical_id="LAW-001",
        version_label=version_label,
        published_date=date(2025, 12, 1),
        effective_date=effective_date,
        source_url="https://example.test/law-001",
        external_id=external_id,
    )
