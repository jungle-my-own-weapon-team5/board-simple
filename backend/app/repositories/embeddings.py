"""Embedding profile과 chunk embedding 저장소 함수입니다."""

from dataclasses import dataclass
from math import sqrt
import re

from sqlalchemy import bindparam
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.document_chunk import LegalDocumentChunk
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding, Vector
from app.models.legal_document import LegalDocument


@dataclass(frozen=True)
class ChunkEmbeddingSearchResult:
    """repository가 반환하는 vector 검색 결과 1건입니다."""

    chunk_embedding: LegalDocumentChunkEmbedding
    score: float


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


def list_searchable_chunk_embeddings(
    db: Session,
    embedding_profile_id: int,
    *,
    document_types: list[str] | None = None,
) -> list[LegalDocumentChunkEmbedding]:
    """vector retrieval 후보가 될 수 있는 chunk embedding row를 조회합니다.

    Repository는 DB에서 명확히 걸러낼 수 있는 조건만 적용합니다. vector score 계산과
    stale checksum 검증은 service 계층에서 수행합니다.
    """
    statement = (
        select(LegalDocumentChunkEmbedding)
        .join(LegalDocumentChunk)
        .join(LegalDocument)
        .where(
            LegalDocumentChunkEmbedding.embedding_profile_id == embedding_profile_id,
            LegalDocumentChunkEmbedding.embedding_status == "embedded",
            LegalDocumentChunkEmbedding.embedding.is_not(None),
            LegalDocument.index_status.not_in(("failed", "replaced")),
            LegalDocument.dedup_status != "duplicate",
            LegalDocument.conflict_status == "none",
        )
        .options(
            selectinload(LegalDocumentChunkEmbedding.chunk)
            .selectinload(LegalDocumentChunk.document)
            .selectinload(LegalDocument.source),
            selectinload(LegalDocumentChunkEmbedding.embedding_profile),
        )
    )
    if document_types:
        statement = statement.where(LegalDocument.document_type.in_(document_types))

    return list(
        db.scalars(
            statement.order_by(LegalDocumentChunkEmbedding.id.asc())
        ).all()
    )


def find_searchable_chunk_embedding_by_article_ref(
    db: Session,
    *,
    embedding_profile_id: int,
    law_title: str,
    article_no: str,
    document_types: list[str] | None = None,
) -> LegalDocumentChunkEmbedding | None:
    """법령명과 조문번호가 정확히 맞는 searchable chunk embedding을 찾습니다.

    필수 조문은 vector score만으로 선택하면 밀릴 수 있으므로, 이미 색인된 공식
    corpus 안에서는 조문 metadata/heading을 우선 사용해 정확 조회합니다.
    """
    normalized_law_title = _normalize_article_match_text(law_title)
    normalized_article_no = _normalize_article_match_text(article_no)
    if not normalized_law_title or not normalized_article_no:
        return None

    candidates = list_searchable_chunk_embeddings(
        db,
        embedding_profile_id,
        document_types=document_types,
    )
    for candidate in candidates:
        chunk = candidate.chunk
        document = chunk.document
        if normalized_law_title not in _normalize_article_match_text(document.title):
            continue
        if _is_invalid_article_chunk(chunk):
            continue
        if _chunk_matches_article_no(chunk, normalized_article_no):
            return candidate
    return None


def search_similar_chunk_embeddings(
    db: Session,
    *,
    embedding_profile_id: int,
    query_vector: list[float],
    top_k: int,
    expected_dimensions: int,
    document_types: list[str] | None = None,
) -> list[ChunkEmbeddingSearchResult]:
    """선택한 embedding profile 안에서 query vector와 가까운 chunk를 검색합니다.

    PostgreSQL에서는 pgvector의 cosine distance 연산자(`<=>`)로 DB가 직접 정렬합니다.
    SQLite 단위 테스트에서는 pgvector가 없으므로 같은 repository 함수 내부에서만
    Python fallback을 사용합니다.
    """
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        return _search_similar_chunk_embeddings_with_pgvector(
            db,
            embedding_profile_id=embedding_profile_id,
            query_vector=query_vector,
            top_k=top_k,
            expected_dimensions=expected_dimensions,
            document_types=document_types,
        )

    return _search_similar_chunk_embeddings_with_python_fallback(
        db,
        embedding_profile_id=embedding_profile_id,
        query_vector=query_vector,
        top_k=top_k,
        expected_dimensions=expected_dimensions,
        document_types=document_types,
    )


def _search_similar_chunk_embeddings_with_pgvector(
    db: Session,
    *,
    embedding_profile_id: int,
    query_vector: list[float],
    top_k: int,
    expected_dimensions: int,
    document_types: list[str] | None,
) -> list[ChunkEmbeddingSearchResult]:
    query_vector_param = bindparam("query_vector", value=query_vector, type_=Vector())
    cosine_distance = LegalDocumentChunkEmbedding.embedding.op("<=>")(
        query_vector_param
    ).label("cosine_distance")
    statement = (
        _base_searchable_chunk_embedding_statement(
            embedding_profile_id=embedding_profile_id,
            document_types=document_types,
        )
        .add_columns(cosine_distance)
        .order_by(cosine_distance.asc(), LegalDocumentChunkEmbedding.chunk_id.asc())
        .limit(top_k)
    )
    rows = db.execute(statement).all()
    scored_results = [
        ChunkEmbeddingSearchResult(
            chunk_embedding=chunk_embedding,
            # pgvector `<=>`는 cosine distance이므로 사용자-facing score는 similarity로 변환합니다.
            score=1.0 - float(cosine_distance_value),
        )
        for chunk_embedding, cosine_distance_value in rows
    ]
    return _filter_dimension_scored_results(
        scored_results,
        top_k=top_k,
        expected_dimensions=expected_dimensions,
    )


def _search_similar_chunk_embeddings_with_python_fallback(
    db: Session,
    *,
    embedding_profile_id: int,
    query_vector: list[float],
    top_k: int,
    expected_dimensions: int,
    document_types: list[str] | None,
) -> list[ChunkEmbeddingSearchResult]:
    candidates = list_searchable_chunk_embeddings(
        db,
        embedding_profile_id,
        document_types=document_types,
    )
    scored_results = [
        ChunkEmbeddingSearchResult(
            chunk_embedding=candidate,
            score=_cosine_similarity(query_vector, candidate.embedding or []),
        )
        for candidate in candidates
    ]
    sorted_results = sorted(
        scored_results,
        key=lambda result: (-result.score, result.chunk_embedding.chunk_id),
    )
    return _filter_dimension_scored_results(
        sorted_results,
        top_k=top_k,
        expected_dimensions=expected_dimensions,
    )


def _base_searchable_chunk_embedding_statement(
    *,
    embedding_profile_id: int,
    document_types: list[str] | None,
):
    statement = (
        select(LegalDocumentChunkEmbedding)
        .join(LegalDocumentChunk)
        .join(LegalDocument)
        .where(
            LegalDocumentChunkEmbedding.embedding_profile_id == embedding_profile_id,
            LegalDocumentChunkEmbedding.embedding_status == "embedded",
            LegalDocumentChunkEmbedding.embedding.is_not(None),
            LegalDocument.index_status.not_in(("failed", "replaced")),
            LegalDocument.dedup_status != "duplicate",
            LegalDocument.conflict_status == "none",
        )
        .options(
            selectinload(LegalDocumentChunkEmbedding.chunk)
            .selectinload(LegalDocumentChunk.document)
            .selectinload(LegalDocument.source),
            selectinload(LegalDocumentChunkEmbedding.embedding_profile),
        )
    )
    if document_types:
        statement = statement.where(LegalDocument.document_type.in_(document_types))
    return statement


def _filter_dimension_scored_results(
    scored_results: list[ChunkEmbeddingSearchResult],
    *,
    top_k: int,
    expected_dimensions: int,
) -> list[ChunkEmbeddingSearchResult]:
    filtered_results: list[ChunkEmbeddingSearchResult] = []
    for result in scored_results:
        chunk_embedding = result.chunk_embedding
        embedding = chunk_embedding.embedding or []
        if len(embedding) != expected_dimensions:
            continue
        filtered_results.append(result)
        if len(filtered_results) == top_k:
            break
    return filtered_results


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(
        left_value * right_value for left_value, right_value in zip(left, right)
    )
    return dot_product / (left_norm * right_norm)


def _chunk_matches_article_no(
    chunk: LegalDocumentChunk,
    normalized_article_no: str,
) -> bool:
    metadata = chunk.metadata_json or {}
    metadata_article_no = _normalize_article_match_text(
        str(metadata.get("article_no") or "")
    )
    heading = _normalize_article_match_text(chunk.heading or "")
    content_prefix = _normalize_article_match_text(chunk.content[:300])
    return (
        metadata_article_no == normalized_article_no
        or normalized_article_no in heading
        or normalized_article_no in content_prefix
    )


def _normalize_article_match_text(value: str) -> str:
    return "".join(value.split()).lower()


def _is_invalid_article_chunk(chunk: LegalDocumentChunk) -> bool:
    content = (chunk.content or "").strip()
    if not content:
        return True
    heading = (chunk.heading or "").strip()
    if heading and _normalize_article_match_text(content) == _normalize_article_match_text(
        heading
    ):
        return True
    match = re.match(r"^(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]*\))?)", content)
    if match is not None and not content[match.end() :].strip():
        return True
    return _has_article_boundary_contamination(chunk)


def _has_article_boundary_contamination(chunk: LegalDocumentChunk) -> bool:
    if not chunk.heading:
        return False
    normalized_heading = _normalize_article_match_text(chunk.heading)
    matches = list(
        re.finditer(r"제\s*\d+\s*조(?:의\s*\d+)?\s*\([^)]*\)", chunk.content or "")
    )
    return any(
        _normalize_article_match_text(match.group(0)) != normalized_heading
        for match in matches[1:]
    )
