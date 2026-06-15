"""`search_law_open_api` MCP tool."""

from __future__ import annotations

from app.core.config import Settings
from app.services.mcp.errors import (
    McpInvalidParamsError,
    McpToolConfigError,
    McpToolExternalServiceError,
    McpToolTimeoutError,
)
from app.services.mcp.types import JsonObject, McpToolCallContext, McpToolDefinition
from app.services.rag.legal_open_api import (
    LawOpenApiAuthError,
    LawOpenApiClient,
    LawOpenApiConfigError,
    LawOpenApiRateLimitError,
    LawOpenApiResponseError,
    LawOpenApiTarget,
    LawOpenApiTimeoutError,
    LawOpenApiUnavailableError,
)

SUPPORTED_TARGETS = {"statute", "case", "interpretation", "admin_appeal"}


def build_search_law_open_api_tool() -> McpToolDefinition:
    return McpToolDefinition(
        name="search_law_open_api",
        description="국가법령정보 Open API 기반 외부 법률 자료 조회",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "target": {
                    "type": "string",
                    "enum": ["statute", "case", "interpretation", "admin_appeal"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
        handler=search_law_open_api_tool,
    )


def search_law_open_api_tool(
    arguments: JsonObject,
    context: McpToolCallContext,
) -> JsonObject:
    query = _required_non_blank_string(arguments, "query")
    target = _optional_target(arguments.get("target", "statute"))
    limit = _optional_positive_int(arguments.get("limit", 5), "limit", max_value=20)
    page = _optional_positive_int(arguments.get("page", 1), "page")
    search_scope = _optional_search_scope(arguments.get("search", 1))

    client = _resolve_client(context)
    try:
        result = client.search(
            query=query,
            target=target,
            limit=limit,
            page=page,
            search_scope=search_scope,
        )
    except ValueError as exc:
        raise McpInvalidParamsError(str(exc)) from exc
    except LawOpenApiConfigError as exc:
        raise McpToolConfigError("LAW_OPEN_API_OC is required") from exc
    except LawOpenApiTimeoutError as exc:
        raise McpToolTimeoutError("Law Open API request timed out") from exc
    except LawOpenApiAuthError as exc:
        raise McpToolExternalServiceError(
            "Law Open API authentication failed",
            error_code="mcp_external_auth_failed",
        ) from exc
    except LawOpenApiRateLimitError as exc:
        raise McpToolExternalServiceError(
            "Law Open API rate limit exceeded",
            error_code="mcp_external_rate_limited",
        ) from exc
    except LawOpenApiUnavailableError as exc:
        raise McpToolExternalServiceError(
            "Law Open API is unavailable",
            error_code="mcp_external_unavailable",
        ) from exc
    except LawOpenApiResponseError as exc:
        raise McpToolExternalServiceError(
            "Law Open API response could not be parsed",
            error_code="mcp_external_response_error",
        ) from exc

    return {
        "tool_name": "search_law_open_api",
        "query": result.query,
        "target": result.target,
        "external_target": result.external_target,
        "total_count": result.total_count,
        "items": [
            {
                "external_id": item.external_id,
                "title": item.title,
                "source_url": item.source_url,
                "summary": item.summary,
                "metadata": item.metadata_json,
            }
            for item in result.items
        ],
    }


def _resolve_client(context: McpToolCallContext) -> LawOpenApiClient:
    if context.law_open_api_client is not None:
        return context.law_open_api_client
    settings = _require_settings(context)
    return LawOpenApiClient(
        oc=settings.law_open_api_oc,
        timeout_seconds=settings.mcp_request_timeout_seconds,
    )


def _require_settings(context: McpToolCallContext) -> Settings:
    if context.settings is None:
        raise McpToolConfigError("MCP settings are required")
    return context.settings


def _required_non_blank_string(arguments: JsonObject, key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise McpInvalidParamsError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_target(value: object) -> LawOpenApiTarget:
    if not isinstance(value, str):
        raise McpInvalidParamsError("target must be a string")
    normalized = value.strip()
    if normalized not in SUPPORTED_TARGETS:
        raise McpInvalidParamsError("target is not supported")
    return normalized  # type: ignore[return-value]


def _optional_positive_int(
    value: object,
    key: str,
    *,
    max_value: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise McpInvalidParamsError(f"{key} must be an integer")
    if value <= 0:
        raise McpInvalidParamsError(f"{key} must be positive")
    if max_value is not None and value > max_value:
        raise McpInvalidParamsError(f"{key} must be less than or equal to {max_value}")
    return value


def _optional_search_scope(value: object) -> int:
    search_scope = _optional_positive_int(value, "search")
    if search_scope not in {1, 2}:
        raise McpInvalidParamsError("search must be 1 or 2")
    return search_scope

