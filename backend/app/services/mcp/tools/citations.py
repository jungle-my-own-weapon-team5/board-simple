"""`verify_citations` MCP tool."""

from __future__ import annotations

from app.repositories import rag_runs as rag_run_repository
from app.services.mcp.errors import McpInvalidParamsError, McpToolConfigError
from app.services.mcp.types import JsonObject, McpToolCallContext, McpToolDefinition


def build_verify_citations_tool() -> McpToolDefinition:
    return McpToolDefinition(
        name="verify_citations",
        description="생성 초안의 citation이 검색 결과에 근거하는지 검증",
        input_schema={
            "type": "object",
            "required": ["run_id", "citations"],
            "properties": {
                "run_id": {"type": "integer"},
                "citations": {"type": "array"},
            },
        },
        handler=verify_citations_tool,
    )


def verify_citations_tool(
    arguments: JsonObject,
    context: McpToolCallContext,
) -> JsonObject:
    db = context.db
    if db is None:
        raise McpToolConfigError("Database session is required")
    if context.user_id is None:
        raise McpToolConfigError("Authenticated user is required")

    run_id = _required_positive_int(arguments.get("run_id"), "run_id")
    citations = arguments.get("citations")
    if not isinstance(citations, list):
        raise McpInvalidParamsError("citations must be an array")

    rag_run = rag_run_repository.get_rag_run(db, run_id)
    if rag_run is None or rag_run.user_id != context.user_id:
        raise McpInvalidParamsError("RAG run was not found")

    retrievals = rag_run_repository.list_retrievals_by_run(db, run_id)
    known_chunk_ids = {retrieval.chunk_id for retrieval in retrievals}
    known_retrieval_ids = {retrieval.id for retrieval in retrievals}
    known_chunk_embedding_ids = {
        retrieval.chunk_embedding_id
        for retrieval in retrievals
        if retrieval.chunk_embedding_id is not None
    }

    valid_citations: list[JsonObject] = []
    invalid_citations: list[JsonObject] = []
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            invalid_citations.append({"index": index, "reason": "citation_not_object"})
            continue

        validation = _validate_citation_reference(
            citation,
            known_chunk_ids=known_chunk_ids,
            known_retrieval_ids=known_retrieval_ids,
            known_chunk_embedding_ids=known_chunk_embedding_ids,
        )
        if validation["valid"]:
            valid_citations.append(validation)
        else:
            invalid_citations.append({"index": index, **validation})

    return {
        "tool_name": "verify_citations",
        "run_id": run_id,
        "valid": not invalid_citations,
        "valid_citations": valid_citations,
        "invalid_citations": invalid_citations,
    }


def _required_positive_int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise McpInvalidParamsError(f"{key} must be an integer")
    if value <= 0:
        raise McpInvalidParamsError(f"{key} must be positive")
    return value


def _validate_citation_reference(
    citation: JsonObject,
    *,
    known_chunk_ids: set[int],
    known_retrieval_ids: set[int],
    known_chunk_embedding_ids: set[int],
) -> JsonObject:
    chunk_id = citation.get("chunk_id")
    if chunk_id is not None:
        normalized_chunk_id = _optional_int_reference(chunk_id, "chunk_id")
        is_valid = normalized_chunk_id in known_chunk_ids
        return {
            "valid": is_valid,
            "reference_type": "chunk_id",
            "chunk_id": normalized_chunk_id,
            "reason": None if is_valid else "citation_not_retrieved",
        }

    retrieval_id = citation.get("retrieval_id")
    if retrieval_id is not None:
        normalized_retrieval_id = _optional_int_reference(retrieval_id, "retrieval_id")
        is_valid = normalized_retrieval_id in known_retrieval_ids
        return {
            "valid": is_valid,
            "reference_type": "retrieval_id",
            "retrieval_id": normalized_retrieval_id,
            "reason": None if is_valid else "citation_not_retrieved",
        }

    chunk_embedding_id = citation.get("chunk_embedding_id")
    if chunk_embedding_id is not None:
        normalized_chunk_embedding_id = _optional_int_reference(
            chunk_embedding_id,
            "chunk_embedding_id",
        )
        is_valid = normalized_chunk_embedding_id in known_chunk_embedding_ids
        return {
            "valid": is_valid,
            "reference_type": "chunk_embedding_id",
            "chunk_embedding_id": normalized_chunk_embedding_id,
            "reason": None if is_valid else "citation_not_retrieved",
        }

    if citation.get("external_id") is not None:
        return {
            "valid": False,
            "reference_type": "external_id",
            "reason": "external_source_verification_not_implemented",
        }
    return {
        "valid": False,
        "reference_type": "unknown",
        "reason": "missing_supported_reference",
    }


def _optional_int_reference(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise McpInvalidParamsError(f"{key} must be an integer")
    return value
