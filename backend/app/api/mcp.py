"""MCP JSON-RPC endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.services.mcp.server import create_default_server
from app.services.mcp.types import McpToolCallContext

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.post("")
def handle_mcp_request(
    payload: Any = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not settings.mcp_server_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server is disabled",
        )

    server = create_default_server(settings.mcp_allowed_tool_names)
    context = McpToolCallContext(
        db=db,
        user_id=current_user.id,
        settings=settings,
        request_id=_extract_request_id(payload),
    )
    return server.handle(payload, context=context)


def _extract_request_id(payload: Any) -> str | int | None:
    if isinstance(payload, dict):
        request_id = payload.get("id")
        if isinstance(request_id, str | int) or request_id is None:
            return request_id
    return None

