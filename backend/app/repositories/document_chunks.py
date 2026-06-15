"""문서 chunk 저장소 함수입니다."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_chunk import LegalDocumentChunk


def add_document_chunk(db: Session, chunk: LegalDocumentChunk) -> None:
    """문서에서 파생된 chunk를 현재 트랜잭션에 추가합니다."""
    db.add(chunk)


def get_document_chunk(db: Session, chunk_id: int) -> LegalDocumentChunk | None:
    return db.get(LegalDocumentChunk, chunk_id)


def list_chunks_by_document(
    db: Session, document_id: int
) -> list[LegalDocumentChunk]:
    """문서에 속한 chunk를 원문 순서대로 조회합니다.

    chunk_index 순서는 citation 표시와 재조립 가능한 본문 확인에 사용됩니다.
    """
    return list(
        db.scalars(
            select(LegalDocumentChunk)
            .where(LegalDocumentChunk.document_id == document_id)
            .order_by(LegalDocumentChunk.chunk_index.asc())
        ).all()
    )
