from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.agent import AgentChatRequest, AgentChatResponse
from app.services.agent import (
    AgentGenerationError,
    AgentNotConfiguredError,
    chat_with_agent,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
def chat_with_board_agent(
    payload: AgentChatRequest,
    current_user: User = Depends(get_current_user),
) -> AgentChatResponse:
    try:
        return chat_with_agent(payload, current_user)
    except AgentNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Agent is not configured.",
        ) from exc
    except AgentGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI Agent failed to generate a response.",
        ) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
