"""MCP server type definitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.core.config import Settings

JsonRpcId = str | int | None
JsonObject = dict[str, Any]
McpToolHandler = Callable[[JsonObject, "McpToolCallContext"], JsonObject]


@dataclass(frozen=True)
class McpToolCallContext:
    """Tool handler가 controller를 우회하지 않고 필요한 실행 문맥을 받는 통로입니다."""

    db: Session | None = None
    user_id: int | None = None
    settings: "Settings | None" = None
    ai_client: Any | None = None
    law_open_api_client: Any | None = None
    request_id: JsonRpcId = None


@dataclass(frozen=True)
class McpToolDefinition:
    name: str
    description: str
    input_schema: JsonObject
    handler: McpToolHandler
    metadata: JsonObject = field(default_factory=dict)

    def to_public_dict(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

