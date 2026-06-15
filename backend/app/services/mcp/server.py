"""MCP JSON-RPC request dispatcher."""

from __future__ import annotations

from typing import Any

from app.services.mcp.errors import (
    McpError,
    McpInvalidParamsError,
    McpInvalidRequestError,
    McpMethodNotFoundError,
)
from app.services.mcp.registry import McpToolRegistry, create_default_registry
from app.services.mcp.types import JsonObject, JsonRpcId, McpToolCallContext

JSONRPC_VERSION = "2.0"


class McpJsonRpcServer:
    """MCP 요청을 JSON-RPC envelope로 검증하고 tool registry로 위임합니다."""

    def __init__(
        self,
        *,
        registry: McpToolRegistry,
        allowed_tool_names: list[str],
    ) -> None:
        self.registry = registry
        self.allowed_tool_names = allowed_tool_names

    def handle(
        self,
        payload: Any,
        *,
        context: McpToolCallContext | None = None,
    ) -> JsonObject:
        request_id = _extract_request_id(payload)
        try:
            request = _validate_request(payload)
            request_id = request["id"]
            method = request["method"]
            params = request["params"]

            if method == "tools/list":
                result = self._handle_tools_list(params)
            elif method == "tools/call":
                result = self._handle_tools_call(
                    params,
                    context or McpToolCallContext(request_id=request_id),
                )
            else:
                raise McpMethodNotFoundError(method)

            return _success_response(request_id, result)
        except McpError as exc:
            return _error_response(request_id, exc)

    def _handle_tools_list(self, params: JsonObject) -> JsonObject:
        if params:
            raise McpInvalidParamsError("tools/list does not accept parameters")
        return {"tools": self.registry.list_tools(self.allowed_tool_names)}

    def _handle_tools_call(
        self,
        params: JsonObject,
        context: McpToolCallContext,
    ) -> JsonObject:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name.strip():
            raise McpInvalidParamsError("Tool name is required")
        if not isinstance(arguments, dict):
            raise McpInvalidParamsError("Tool arguments must be an object")
        return self.registry.call_tool(
            tool_name=name,
            arguments=arguments,
            context=context,
            allowed_tool_names=self.allowed_tool_names,
        )


def create_default_server(allowed_tool_names: list[str]) -> McpJsonRpcServer:
    return McpJsonRpcServer(
        registry=create_default_registry(),
        allowed_tool_names=allowed_tool_names,
    )


def _validate_request(payload: Any) -> JsonObject:
    if not isinstance(payload, dict):
        raise McpInvalidRequestError()
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise McpInvalidRequestError("jsonrpc must be 2.0")
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise McpInvalidRequestError("method is required")
    request_id = payload.get("id")
    if request_id is not None and not isinstance(request_id, str | int):
        raise McpInvalidRequestError("id must be a string, integer, or null")
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise McpInvalidParamsError("params must be an object")
    return {
        "id": request_id,
        "method": method,
        "params": params,
    }


def _extract_request_id(payload: Any) -> JsonRpcId:
    if isinstance(payload, dict):
        request_id = payload.get("id")
        if isinstance(request_id, str | int) or request_id is None:
            return request_id
    return None


def _success_response(request_id: JsonRpcId, result: JsonObject) -> JsonObject:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def _error_response(request_id: JsonRpcId, error: McpError) -> JsonObject:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": error.to_error_object(),
    }

