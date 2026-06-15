"""MCP tool registry."""

from __future__ import annotations

from collections.abc import Iterable

from app.services.mcp.errors import (
    McpToolExecutionError,
    McpToolNotAllowedError,
    McpToolNotFoundError,
    McpToolNotImplementedError,
)
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
        except McpToolNotImplementedError:
            raise
        except Exception as exc:
            raise McpToolExecutionError() from exc


def create_default_registry() -> McpToolRegistry:
    return McpToolRegistry(
        [
            McpToolDefinition(
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
                        "score_threshold": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "max_chunks_per_document": {
                            "type": "integer",
                            "minimum": 1,
                        },
                        "filters": {"type": "object"},
                    },
                },
                handler=_not_implemented_handler("search_legal_documents"),
            ),
            McpToolDefinition(
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
                handler=_not_implemented_handler("search_law_open_api"),
            ),
            McpToolDefinition(
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
                handler=_not_implemented_handler("verify_citations"),
            ),
        ]
    )


def _not_implemented_handler(tool_name: str):
    def handler(
        arguments: JsonObject,
        context: McpToolCallContext,
    ) -> JsonObject:
        raise McpToolNotImplementedError(tool_name)

    return handler


def _deduplicate_names(names: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))

