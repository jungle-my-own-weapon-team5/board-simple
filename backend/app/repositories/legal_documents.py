"""법률 출처/문서 저장소 함수입니다.

Repository는 DB 조회와 세션 등록만 담당하고 commit/rollback은 서비스 계층에서 처리합니다.
"""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.legal_document import LegalDocument
from app.models.legal_source import LegalSource


def _nullable_equals(column: Any, value: Any) -> Any:
    """NULL 값도 같은 문서 식별 조건으로 비교하기 위한 보조 함수입니다."""
    return column.is_(None) if value is None else column == value


def _same_version_filters(
    *,
    document_type: str,
    canonical_id: str | None,
    version_label: str | None,
    effective_date: date | None,
) -> tuple[Any, ...]:
    """같은 법령/문서의 같은 버전인지 판단하는 공통 조회 조건입니다."""
    return (
        LegalDocument.document_type == document_type,
        _nullable_equals(LegalDocument.canonical_id, canonical_id),
        _nullable_equals(LegalDocument.version_label, version_label),
        _nullable_equals(LegalDocument.effective_date, effective_date),
    )


def add_legal_source(db: Session, source: LegalSource) -> None:
    """출처 row를 현재 트랜잭션에 추가합니다."""
    db.add(source)


def get_legal_source(db: Session, source_id: int) -> LegalSource | None:
    return db.get(LegalSource, source_id)


def find_legal_source_by_provider_external_id(
    db: Session, *, provider: str, external_id: str | None
) -> LegalSource | None:
    """외부 provider 식별자가 있는 출처 row를 조회합니다.

    같은 API 응답 또는 fixture를 반복 ingestion할 때 source unique 제약을
    피하고, 동일 출처에서 여러 문서 버전이 파생될 수 있게 합니다.
    """
    if external_id is None:
        return None

    return db.scalar(
        select(LegalSource).where(
            LegalSource.provider == provider,
            LegalSource.external_id == external_id,
        )
    )


def add_legal_document(db: Session, document: LegalDocument) -> None:
    """법률 문서 row를 현재 트랜잭션에 추가합니다."""
    db.add(document)


def get_legal_document(db: Session, document_id: int) -> LegalDocument | None:
    return db.scalar(
        select(LegalDocument)
        .where(LegalDocument.id == document_id)
        .options(
            selectinload(LegalDocument.source),
            selectinload(LegalDocument.duplicate_of),
        )
    )


def find_indexed_document_by_identity(
    db: Session,
    *,
    document_type: str,
    canonical_id: str | None,
    version_label: str | None,
    effective_date: date | None,
    published_date: date | None,
) -> LegalDocument | None:
    """공식 source preflight metadata와 같은 indexed 문서를 찾습니다.

    전문 API를 다시 호출하기 전에 이 후보가 있고 chunk/embedding이 최신이면 기존 DB
    데이터를 재사용할 수 있습니다. 충돌 검토나 중복 문서는 재사용 후보에서 제외합니다.
    """
    return db.scalar(
        select(LegalDocument)
        .where(
            *_same_version_filters(
                document_type=document_type,
                canonical_id=canonical_id,
                version_label=version_label,
                effective_date=effective_date,
            ),
            _nullable_equals(LegalDocument.published_date, published_date),
            LegalDocument.index_status == "indexed",
            LegalDocument.dedup_status != "duplicate",
            LegalDocument.conflict_status == "none",
        )
        .order_by(LegalDocument.id.asc())
        .limit(1)
    )


def find_duplicate_document_candidate(
    db: Session,
    *,
    document_type: str,
    canonical_id: str | None,
    version_label: str | None,
    effective_date: date | None,
    normalized_checksum: str | None,
) -> LegalDocument | None:
    """같은 버전이며 정규화 해시가 같은 대표 문서 후보를 찾습니다.

    최종 중복 판정과 상태 변경은 ingestion 서비스에서 수행합니다.
    """
    if normalized_checksum is None:
        return None

    return db.scalar(
        select(LegalDocument)
        .where(
            *_same_version_filters(
                document_type=document_type,
                canonical_id=canonical_id,
                version_label=version_label,
                effective_date=effective_date,
            ),
            LegalDocument.normalized_checksum == normalized_checksum,
            LegalDocument.dedup_status != "duplicate",
        )
        .order_by(LegalDocument.id.asc())
        .limit(1)
    )


def list_conflicting_document_candidates(
    db: Session,
    *,
    document_type: str,
    canonical_id: str | None,
    version_label: str | None,
    effective_date: date | None,
    normalized_checksum: str | None,
) -> list[LegalDocument]:
    """같은 버전인데 정규화 해시가 다른 문서 후보를 조회합니다.

    이 결과가 있으면 자동 병합하지 않고 conflict review 대상으로 넘겨야 합니다.
    """
    if normalized_checksum is None:
        return []

    return list(
        db.scalars(
            select(LegalDocument)
            .where(
                *_same_version_filters(
                    document_type=document_type,
                    canonical_id=canonical_id,
                    version_label=version_label,
                    effective_date=effective_date,
                ),
                LegalDocument.normalized_checksum != normalized_checksum,
                LegalDocument.dedup_status != "duplicate",
            )
            .order_by(LegalDocument.id.asc())
        ).all()
    )
