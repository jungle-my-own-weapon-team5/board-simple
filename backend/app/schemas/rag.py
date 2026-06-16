"""RAG 검색 API의 요청/응답 스키마입니다."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.services.rag.retrieval import RagSearchResultItem, SearchLegalDocumentsResult

SearchMode = Literal["focused_answer", "issue_spotting"]
DocumentType = Literal[
    "statute",
    "case",
    "interpretation",
    "admin_appeal",
    "user_file",
    "memo",
]


class RagSearchFilters(BaseModel):
    """검색 후보를 줄이기 위한 metadata filter입니다."""

    document_type: DocumentType | None = None
    document_types: list[DocumentType] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_exclusive_document_type(self) -> "RagSearchFilters":
        if self.document_type is not None and self.document_types is not None:
            raise ValueError("use either document_type or document_types")
        return self


class RagSearchCreate(BaseModel):
    """답변 생성 없이 vector retrieval만 수행하는 요청입니다."""

    query: str = Field(min_length=1, max_length=5000)
    search_mode: SearchMode = "focused_answer"
    top_k: int | None = Field(default=None, ge=1, le=100)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    max_chunks_per_document: int | None = Field(default=None, ge=1, le=100)
    embedding_profile_id: int | None = Field(default=None, ge=1)
    filters: RagSearchFilters | None = None


class RagSearchItemRead(BaseModel):
    """사용자에게 반환할 검색 결과 chunk입니다."""

    retrieval_id: int | None
    chunk_embedding_id: int
    chunk_id: int
    document_id: int
    rank: int
    score: float
    title: str
    source_url: str | None
    heading: str | None
    content: str
    metadata: dict[str, object]

    @classmethod
    def from_service_item(cls, item: RagSearchResultItem) -> "RagSearchItemRead":
        return cls(
            retrieval_id=item.retrieval_id,
            chunk_embedding_id=item.chunk_embedding_id,
            chunk_id=item.chunk_id,
            document_id=item.document_id,
            rank=item.rank,
            score=item.score,
            title=item.title,
            source_url=item.source_url,
            heading=item.heading,
            content=item.content,
            metadata=item.metadata_json,
        )


class RagSearchRead(BaseModel):
    """검색 실행 metadata와 결과 목록입니다."""

    run_id: int
    query: str
    search_mode: SearchMode
    top_k: int
    score_threshold: float | None
    max_chunks_per_document: int | None
    embedding_profile_id: int
    embedding_provider: str
    embedding_model_name: str
    embedding_dimensions: int
    items: list[RagSearchItemRead]

    @classmethod
    def from_service_result(cls, result: SearchLegalDocumentsResult) -> "RagSearchRead":
        return cls(
            run_id=result.run_id,
            query=result.query,
            search_mode=result.search_mode,
            top_k=result.top_k,
            score_threshold=result.score_threshold,
            max_chunks_per_document=result.max_chunks_per_document,
            embedding_profile_id=result.embedding_profile_id,
            embedding_provider=result.embedding_provider,
            embedding_model_name=result.embedding_model_name,
            embedding_dimensions=result.embedding_dimensions,
            items=[
                RagSearchItemRead.from_service_item(item) for item in result.results
            ],
        )
