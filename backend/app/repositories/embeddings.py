"""Embedding profile과 chunk embedding 저장소 함수입니다."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding


def add_embedding_profile(db: Session, profile: EmbeddingProfile) -> None:
    """embedding 검색 공간을 정의하는 profile을 현재 트랜잭션에 추가합니다."""
    db.add(profile)


def get_embedding_profile(db: Session, profile_id: int) -> EmbeddingProfile | None:
    return db.get(EmbeddingProfile, profile_id)


def find_embedding_profile(
    db: Session,
    *,
    provider: str,
    model_name: str,
    dimensions: int,
    distance_metric: str = "cosine",
) -> EmbeddingProfile | None:
    """provider/model/dimension/metric 조합으로 기존 profile을 찾습니다."""
    return db.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.provider == provider,
            EmbeddingProfile.model_name == model_name,
            EmbeddingProfile.dimensions == dimensions,
            EmbeddingProfile.distance_metric == distance_metric,
        )
    )


def get_or_create_embedding_profile(
    db: Session,
    *,
    provider: str,
    model_name: str,
    dimensions: int,
    distance_metric: str = "cosine",
    vector_type: str = "vector",
    status: str = "active",
    is_default: bool = False,
    metadata_json: dict[str, object] | None = None,
) -> EmbeddingProfile:
    """같은 검색 공간 profile이 있으면 재사용하고, 없으면 새로 만듭니다."""
    existing_profile = find_embedding_profile(
        db,
        provider=provider,
        model_name=model_name,
        dimensions=dimensions,
        distance_metric=distance_metric,
    )
    if existing_profile is not None:
        return existing_profile

    profile = EmbeddingProfile(
        provider=provider,
        model_name=model_name,
        dimensions=dimensions,
        distance_metric=distance_metric,
        vector_type=vector_type,
        status=status,
        is_default=is_default,
        metadata_json=metadata_json or {},
    )
    db.add(profile)
    db.flush()
    return profile


def list_active_embedding_profiles(db: Session) -> list[EmbeddingProfile]:
    """retrieval에서 선택 가능한 active profile 목록을 조회합니다."""
    return list(
        db.scalars(
            select(EmbeddingProfile)
            .where(EmbeddingProfile.status == "active")
            .order_by(EmbeddingProfile.is_default.desc(), EmbeddingProfile.id.asc())
        ).all()
    )


def add_chunk_embedding(
    db: Session, chunk_embedding: LegalDocumentChunkEmbedding
) -> None:
    """chunk와 profile의 embedding row를 현재 트랜잭션에 추가합니다."""
    db.add(chunk_embedding)


def get_chunk_embedding(
    db: Session, chunk_embedding_id: int
) -> LegalDocumentChunkEmbedding | None:
    return db.get(LegalDocumentChunkEmbedding, chunk_embedding_id)


def find_chunk_embedding(
    db: Session,
    *,
    chunk_id: int,
    embedding_profile_id: int,
) -> LegalDocumentChunkEmbedding | None:
    """chunk/profile 조합의 embedding row를 찾습니다."""
    return db.scalar(
        select(LegalDocumentChunkEmbedding).where(
            LegalDocumentChunkEmbedding.chunk_id == chunk_id,
            LegalDocumentChunkEmbedding.embedding_profile_id == embedding_profile_id,
        )
    )


def list_chunk_embeddings_by_chunk(
    db: Session, chunk_id: int
) -> list[LegalDocumentChunkEmbedding]:
    """하나의 chunk가 가진 모든 profile별 embedding을 조회합니다."""
    return list(
        db.scalars(
            select(LegalDocumentChunkEmbedding)
            .where(LegalDocumentChunkEmbedding.chunk_id == chunk_id)
            .order_by(LegalDocumentChunkEmbedding.embedding_profile_id.asc())
        ).all()
    )


def list_chunk_embeddings_by_profile(
    db: Session,
    embedding_profile_id: int,
    *,
    embedding_status: str | None = None,
) -> list[LegalDocumentChunkEmbedding]:
    """특정 profile로 생성된 chunk embedding을 조회합니다."""
    statement = select(LegalDocumentChunkEmbedding).where(
        LegalDocumentChunkEmbedding.embedding_profile_id == embedding_profile_id
    )
    if embedding_status is not None:
        statement = statement.where(
            LegalDocumentChunkEmbedding.embedding_status == embedding_status
        )
    return list(
        db.scalars(
            statement.order_by(LegalDocumentChunkEmbedding.chunk_id.asc())
        ).all()
    )
