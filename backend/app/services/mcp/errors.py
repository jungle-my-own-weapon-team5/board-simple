"""MCP JSON-RPC error types."""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class JsonRpcErrorCode(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class McpError(Exception):
    """JSON-RPC error로 안전하게 변환할 수 있는 MCP 예외입니다."""

    def __init__(
        self,
        *,
        code: JsonRpcErrorCode,
        message: str,
        error_code: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.error_code = error_code
        self.data = {"error_code": error_code, **(data or {})}

    def to_error_object(self) -> dict[str, Any]:
        return {
            "code": int(self.code),
            "message": self.message,
            "data": self.data,
        }


class McpInvalidRequestError(McpError):
    def __init__(self, message: str = "Invalid JSON-RPC request") -> None:
        super().__init__(
            code=JsonRpcErrorCode.INVALID_REQUEST,
            message=message,
            error_code="mcp_invalid_request",
        )


class McpMethodNotFoundError(McpError):
    def __init__(self, method: str) -> None:
        super().__init__(
            code=JsonRpcErrorCode.METHOD_NOT_FOUND,
            message="Method not found",
            error_code="mcp_method_not_found",
        )


class McpInvalidParamsError(McpError):
    def __init__(self, message: str = "Invalid tool arguments") -> None:
        super().__init__(
            code=JsonRpcErrorCode.INVALID_PARAMS,
            message=message,
            error_code="mcp_invalid_arguments",
        )


class McpToolNotAllowedError(McpError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            code=JsonRpcErrorCode.INVALID_PARAMS,
            message="Tool is not allowed",
            error_code="mcp_tool_not_allowed",
        )


class McpToolNotFoundError(McpError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            code=JsonRpcErrorCode.INVALID_PARAMS,
            message="Tool not found",
            error_code="mcp_tool_not_found",
        )


class McpToolNotImplementedError(McpError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            code=JsonRpcErrorCode.INTERNAL_ERROR,
            message="Tool is not implemented",
            error_code="mcp_tool_not_implemented",
        )


class McpToolConfigError(McpError):
    def __init__(self, message: str = "Tool is not configured") -> None:
        super().__init__(
            code=JsonRpcErrorCode.INTERNAL_ERROR,
            message=message,
            error_code="mcp_tool_config_error",
        )


class McpToolTimeoutError(McpError):
    def __init__(self, message: str = "Tool request timed out") -> None:
        super().__init__(
            code=JsonRpcErrorCode.INTERNAL_ERROR,
            message=message,
            error_code="mcp_tool_timeout",
        )


class McpToolExternalServiceError(McpError):
    def __init__(
        self,
        message: str = "External legal source request failed",
        *,
        error_code: str = "mcp_external_service_error",
    ) -> None:
        super().__init__(
            code=JsonRpcErrorCode.INTERNAL_ERROR,
            message=message,
            error_code=error_code,
        )


class McpToolExecutionError(McpError):
    def __init__(self) -> None:
        super().__init__(
            code=JsonRpcErrorCode.INTERNAL_ERROR,
            message="Tool execution failed",
            error_code="mcp_tool_execution_failed",
        )

