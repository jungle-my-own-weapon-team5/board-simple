"""MCP tool registry."""

from __future__ import annotations

from collections.abc import Iterable

from app.services.mcp.errors import (
    McpError,
    McpToolExecutionError,
    McpToolNotAllowedError,
    McpToolNotFoundError,
)
from app.services.mcp.tools.citations import build_verify_citations_tool
from app.services.mcp.tools.legal_documents import build_search_legal_documents_tool
from app.services.mcp.tools.legal_open_api import build_search_law_open_api_tool
from app.services.mcp.types import JsonObject, McpToolCallContext, McpToolDefinition


class McpToolRegistry:
    """MCP tool 정의와 실행 handler를 allowlist 기준으로 관리합니다."""

    def __init__(self, tools: Iterable[McpToolDefinition] | None = None) -> None:
        self._tools: dict[str, McpToolDefinition] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: McpToolDefinition) -> None:
        self._tools[tool.name] = tool

    def list_tools(self, allowed_tool_names: Iterable[str]) -> list[JsonObject]:
        return [
            self._tools[name].to_public_dict()
            for name in _deduplicate_names(allowed_tool_names)
            if name in self._tools
        ]

    def call_tool(
        self,
        *,
        tool_name: str,
        arguments: JsonObject,
        context: McpToolCallContext,
        allowed_tool_names: Iterable[str],
    ) -> JsonObject:
        allowed = set(_deduplicate_names(allowed_tool_names))
        if tool_name not in allowed:
            raise McpToolNotAllowedError(tool_name)
        tool = self._tools.get(tool_name)
        if tool is None:
            raise McpToolNotFoundError(tool_name)
        try:
            return tool.handler(arguments, context)
        except McpError:
            raise
        except Exception as exc:
            raise McpToolExecutionError() from exc


def create_default_registry() -> McpToolRegistry:
    return McpToolRegistry(
        [
            build_search_legal_documents_tool(),
            build_search_law_open_api_tool(),
            build_verify_citations_tool(),
        ]
    )


def _deduplicate_names(names: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))

