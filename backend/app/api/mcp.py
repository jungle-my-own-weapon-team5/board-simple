from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.mcp_server import handle_json_rpc

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.post("")
def mcp_endpoint(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return handle_json_rpc(db, settings, payload)
