from collections.abc import Generator
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import LegalDocument, LegalDocumentChunk, LegalSource, User
from app.models.rag_run import AgentStep, RagRetrieval, RagRun
from app.repositories import document_chunks, legal_documents, rag_runs


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


def _create_source(db: Session) -> LegalSource:
    source = LegalSource(
        provider="fixture",
        source_type="law",
        external_id="law-001",
        source_url="https://example.test/law-001",
    )
    legal_documents.add_legal_source(db, source)
    db.flush()
    return source


def _create_document(
    db: Session,
    source: LegalSource,
    *,
    normalized_checksum: str = "normalized-1",
    effective_date: date = date(2026, 1, 1),
    version_label: str | None = "2026-01-01",
    dedup_status: str = "unique",
    conflict_status: str = "none",
    duplicate_of_document_id: int | None = None,
) -> LegalDocument:
    document = LegalDocument(
        source_id=source.id,
        document_type="statute",
        title="테스트 법령",
        canonical_id="LAW-001",
        version_label=version_label,
        published_date=date(2025, 12, 1),
        effective_date=effective_date,
        raw_text="제1조 원문",
        normalized_text="제1조 원문",
        raw_checksum=f"raw-{normalized_checksum}",
        normalized_checksum=normalized_checksum,
        dedup_status=dedup_status,
        conflict_status=conflict_status,
        duplicate_of_document_id=duplicate_of_document_id,
    )
    legal_documents.add_legal_document(db, document)
    db.flush()
    return document


def test_legal_document_persists_checksum_and_status_fields(db: Session) -> None:
    source = _create_source(db)
    document = _create_document(db, source)

    loaded = legal_documents.get_legal_document(db, document.id)

    assert loaded is not None
    assert loaded.raw_checksum == "raw-normalized-1"
    assert loaded.normalized_checksum == "normalized-1"
    assert loaded.dedup_status == "unique"
    assert loaded.conflict_status == "none"
    assert loaded.source.provider == "fixture"


def test_duplicate_candidate_uses_same_version_and_normalized_checksum(
    db: Session,
) -> None:
    source = _create_source(db)
    original = _create_document(db, source)
    duplicate = _create_document(
        db,
        source,
        dedup_status="duplicate",
        duplicate_of_document_id=original.id,
    )

    candidate = legal_documents.find_duplicate_document_candidate(
        db,
        document_type=duplicate.document_type,
        canonical_id=duplicate.canonical_id,
        version_label=duplicate.version_label,
        effective_date=duplicate.effective_date,
        normalized_checksum=duplicate.normalized_checksum,
    )

    assert candidate is not None
    assert candidate.id == original.id


def test_conflict_candidate_requires_same_version_but_different_normalized_checksum(
    db: Session,
) -> None:
    source = _create_source(db)
    existing = _create_document(db, source, normalized_checksum="normalized-1")

    conflicts = legal_documents.list_conflicting_document_candidates(
        db,
        document_type="statute",
        canonical_id="LAW-001",
        version_label="2026-01-01",
        effective_date=date(2026, 1, 1),
        normalized_checksum="normalized-2",
    )

    assert [document.id for document in conflicts] == [existing.id]


def test_different_effective_date_is_treated_as_separate_version(
    db: Session,
) -> None:
    source = _create_source(db)
    _create_document(db, source, normalized_checksum="normalized-1")

    candidate = legal_documents.find_duplicate_document_candidate(
        db,
        document_type="statute",
        canonical_id="LAW-001",
        version_label="2026-02-01",
        effective_date=date(2026, 2, 1),
        normalized_checksum="normalized-1",
    )
    conflicts = legal_documents.list_conflicting_document_candidates(
        db,
        document_type="statute",
        canonical_id="LAW-001",
        version_label="2026-02-01",
        effective_date=date(2026, 2, 1),
        normalized_checksum="normalized-2",
    )

    assert candidate is None
    assert conflicts == []


def test_chunks_rag_runs_steps_and_retrievals_are_persisted_in_order(
    db: Session,
) -> None:
    source = _create_source(db)
    document = _create_document(db, source)
    chunk = LegalDocumentChunk(
        document_id=document.id,
        chunk_index=0,
        heading="제1조",
        content="테스트 조문 내용",
        token_count=12,
    )
    document_chunks.add_document_chunk(db, chunk)
    user = User(
        email="rag@example.com",
        password_hash="hashed-password",
        nickname="rag-user",
    )
    db.add(user)
    db.flush()

    rag_run = RagRun(
        user_id=user.id,
        run_type="legal_qa",
        query="테스트 질의",
        embedding_provider="mock",
        embedding_model_name="mock-embedding",
        prompt_version="v1",
    )
    rag_runs.add_rag_run(db, rag_run)
    db.flush()

    rag_runs.add_agent_step(
        db,
        AgentStep(
            rag_run_id=rag_run.id,
            step_index=0,
            step_type="retrieve",
            status="completed",
            input_json={"query": "테스트 질의"},
            output_json={"count": 1},
        ),
    )
    rag_runs.add_rag_retrieval(
        db,
        RagRetrieval(
            rag_run_id=rag_run.id,
            chunk_id=chunk.id,
            rank=1,
            score=0.9,
            retrieval_type="vector",
        ),
    )
    db.flush()

    assert document_chunks.list_chunks_by_document(db, document.id) == [chunk]
    assert [step.step_index for step in rag_runs.list_agent_steps_by_run(db, rag_run.id)] == [
        0
    ]
    assert [
        retrieval.chunk_id for retrieval in rag_runs.list_retrievals_by_run(db, rag_run.id)
    ] == [chunk.id]
