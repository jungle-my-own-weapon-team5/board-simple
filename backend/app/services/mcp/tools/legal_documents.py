"""`search_legal_documents` MCP tool."""

from __future__ import annotations

from app.core.config import Settings
from app.repositories import embeddings as embedding_repository
from app.services.ai.client import AIClient
from app.services.mcp.errors import McpInvalidParamsError, McpToolConfigError
from app.services.mcp.types import JsonObject, McpToolCallContext, McpToolDefinition
from app.services.rag.embedding_profiles import (
    EmbeddingProfileConfigError,
    get_active_or_create_default_embedding_profile,
)
from app.services.rag.retrieval import search_legal_documents

SUPPORTED_SEARCH_MODES = {"focused_answer", "issue_spotting"}


def build_search_legal_documents_tool() -> McpToolDefinition:
    return McpToolDefinition(
        name="search_legal_documents",
        description="내부 pgvector 기반 법률 문서 검색",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "search_mode": {
                    "type": "string",
                    "enum": ["focused_answer", "issue_spotting"],
                },
                "top_k": {"type": "integer", "minimum": 1},
                "score_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "max_chunks_per_document": {"type": "integer", "minimum": 1},
                "filters": {"type": "object"},
            },
        },
        handler=search_legal_documents_tool,
    )


def search_legal_documents_tool(
    arguments: JsonObject,
    context: McpToolCallContext,
) -> JsonObject:
    db = context.db
    if db is None:
        raise McpToolConfigError("Database session is required")
    if context.user_id is None:
        raise McpToolConfigError("Authenticated user is required")
    settings = _require_settings(context)

    query = _required_non_blank_string(arguments, "query")
    search_mode = _optional_search_mode(arguments.get("search_mode", "focused_answer"))
    top_k = _optional_positive_int(arguments.get("top_k"), "top_k")
    score_threshold = _optional_score_threshold(arguments.get("score_threshold"))
    max_chunks_per_document = _optional_positive_int(
        arguments.get("max_chunks_per_document"),
        "max_chunks_per_document",
    )
    filters = _optional_object(arguments.get("filters"), "filters")
    document_types = _document_types_from_filters(filters)
    embedding_profile = _select_embedding_profile(
        db,
        settings=settings,
        embedding_profile_id=filters.get("embedding_profile_id"),
    )
    ai_client = context.ai_client or AIClient(settings)

    try:
        result = search_legal_documents(
            db,
            user_id=context.user_id,
            query=query,
            embedding_profile=embedding_profile,
            ai_client=ai_client,
            search_mode=search_mode,
            top_k=top_k,
            score_threshold=score_threshold,
            max_chunks_per_document=max_chunks_per_document,
            prompt_version=settings.rag_prompt_version,
            timeout_seconds=settings.ai_request_timeout_seconds,
            document_types=document_types,
        )
    except ValueError as exc:
        raise McpInvalidParamsError(str(exc)) from exc

    return {
        "tool_name": "search_legal_documents",
        "run_id": result.run_id,
        "status": result.status,
        "search_mode": result.search_mode,
        "top_k": result.top_k,
        "score_threshold": result.score_threshold,
        "max_chunks_per_document": result.max_chunks_per_document,
        "embedding_profile_id": result.embedding_profile_id,
        "embedding_provider": result.embedding_provider,
        "embedding_model_name": result.embedding_model_name,
        "embedding_dimensions": result.embedding_dimensions,
        "items": [
            {
                "retrieval_id": item.retrieval_id,
                "chunk_embedding_id": item.chunk_embedding_id,
                "chunk_id": item.chunk_id,
                "document_id": item.document_id,
                "rank": item.rank,
                "score": item.score,
                "title": item.title,
                "source_url": item.source_url,
                "heading": item.heading,
                "content": item.content,
                "metadata": item.metadata_json,
            }
            for item in result.results
        ],
        "error_code": result.error_code,
        "error_message": result.error_message,
    }


def _require_settings(context: McpToolCallContext) -> Settings:
    if context.settings is None:
        raise McpToolConfigError("MCP settings are required")
    return context.settings


def _required_non_blank_string(arguments: JsonObject, key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise McpInvalidParamsError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_search_mode(value: object) -> str:
    if not isinstance(value, str):
        raise McpInvalidParamsError("search_mode must be a string")
    normalized = value.strip()
    if normalized not in SUPPORTED_SEARCH_MODES:
        raise McpInvalidParamsError("search_mode is not supported")
    return normalized


def _optional_positive_int(value: object, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise McpInvalidParamsError(f"{key} must be an integer")
    if value <= 0:
        raise McpInvalidParamsError(f"{key} must be positive")
    return value


def _optional_score_threshold(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise McpInvalidParamsError("score_threshold must be a number")
    score_threshold = float(value)
    if not 0 <= score_threshold <= 1:
        raise McpInvalidParamsError("score_threshold must be between 0 and 1")
    return score_threshold


def _optional_object(value: object, key: str) -> JsonObject:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise McpInvalidParamsError(f"{key} must be an object")
    return value


def _document_types_from_filters(filters: JsonObject) -> list[str] | None:
    document_type = filters.get("document_type")
    document_types = filters.get("document_types")
    if document_type is not None and document_types is not None:
        raise McpInvalidParamsError("use either document_type or document_types")
    if document_type is not None:
        if not isinstance(document_type, str) or not document_type.strip():
            raise McpInvalidParamsError("document_type must be a non-empty string")
        return [document_type.strip()]
    if document_types is None:
        return None
    if not isinstance(document_types, list) or not all(
        isinstance(item, str) and item.strip() for item in document_types
    ):
        raise McpInvalidParamsError("document_types must be a string array")
    return [item.strip() for item in document_types]


def _select_embedding_profile(
    db,
    *,
    settings: Settings,
    embedding_profile_id: object,
):
    if embedding_profile_id is not None:
        if isinstance(embedding_profile_id, bool) or not isinstance(
            embedding_profile_id, int
        ):
            raise McpInvalidParamsError("embedding_profile_id must be an integer")
        profile = embedding_repository.get_embedding_profile(db, embedding_profile_id)
        if profile is None:
            raise McpInvalidParamsError("embedding_profile_id was not found")
        return profile

    try:
        return get_active_or_create_default_embedding_profile(db, settings)
    except EmbeddingProfileConfigError as exc:
        raise McpToolConfigError(str(exc)) from exc

