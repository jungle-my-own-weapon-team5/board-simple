"""Embedding profile selection helpers for RAG entry points."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.embedding import EmbeddingProfile
from app.repositories import embeddings as embedding_repository


class EmbeddingProfileConfigError(ValueError):
    """기본 embedding profile을 만들 수 없을 때 사용하는 설정 오류입니다."""


def get_or_create_default_embedding_profile(
    db: Session,
    settings: Settings,
) -> EmbeddingProfile:
    """환경변수로 지정한 기본 검색 공간을 DB profile row로 고정합니다."""

    provider = settings.ai_embedding_provider.strip()
    model_name = settings.ai_embedding_model.strip()
    dimensions = settings.ai_embedding_dimensions
    if not provider:
        raise EmbeddingProfileConfigError("AI_EMBEDDING_PROVIDER is required")
    if not model_name:
        raise EmbeddingProfileConfigError("AI_EMBEDDING_MODEL is required")
    if dimensions is None or dimensions <= 0:
        raise EmbeddingProfileConfigError(
            "AI_EMBEDDING_DIMENSIONS must be a positive integer"
        )

    profile = embedding_repository.get_or_create_embedding_profile(
        db,
        provider=provider,
        model_name=model_name,
        dimensions=dimensions,
        distance_metric="cosine",
        vector_type="vector",
        status="active",
        is_default=True,
        metadata_json={"configured_by": "settings"},
    )
    _ensure_profile_is_active_default(profile)
    db.flush()
    return profile


def get_active_or_create_default_embedding_profile(
    db: Session,
    settings: Settings,
) -> EmbeddingProfile:
    """기존 active profile을 우선 사용하고, 없을 때만 기본 profile을 만듭니다."""

    active_profiles = embedding_repository.list_active_embedding_profiles(db)
    if active_profiles:
        return active_profiles[0]
    return get_or_create_default_embedding_profile(db, settings)


def _ensure_profile_is_active_default(profile: EmbeddingProfile) -> None:
    """기존 row를 재사용할 때도 현재 설정의 기본 profile로 사용할 수 있게 맞춥니다."""

    profile.status = "active"
    profile.is_default = True
    metadata = dict(profile.metadata_json or {})
    metadata.setdefault("configured_by", "settings")
    profile.metadata_json = metadata
