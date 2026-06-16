from __future__ import annotations

from typing import Any, TypedDict

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.user import User
from app.schemas.ai import AgentChatPageContext, AgentRunResponse, AgentStep
from app.services.ai_runtime import run_agent


class ChatAgentState(TypedDict, total=False):
    message: str
    page_context: dict[str, Any] | None
    user_nickname: str
    goal: str
    topic: str
    graph_mode: str
    response: AgentRunResponse


def run_chat_agent(
    db: Session,
    settings: Settings,
    message: str,
    page_context: AgentChatPageContext | None,
    current_user: User,
) -> AgentRunResponse:
    initial_state: ChatAgentState = {
        "message": message.strip(),
        "page_context": page_context.model_dump() if page_context else None,
        "user_nickname": current_user.nickname,
        "graph_mode": "langgraph",
    }

    try:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(ChatAgentState)
        graph.add_node("prepare_context", _prepare_context_node)
        graph.add_node("run_retrieval_agent", lambda state: _run_retrieval_agent_node(state, db, settings))
        graph.set_entry_point("prepare_context")
        graph.add_edge("prepare_context", "run_retrieval_agent")
        graph.add_edge("run_retrieval_agent", END)
        result = graph.compile().invoke(initial_state)
    except ImportError:
        fallback_state: ChatAgentState = {**initial_state, "graph_mode": "local_fallback"}
        prepared = {**fallback_state, **_prepare_context_node(fallback_state)}
        result = {**prepared, **_run_retrieval_agent_node(prepared, db, settings)}

    return result["response"]


def _prepare_context_node(state: ChatAgentState) -> ChatAgentState:
    context = state.get("page_context") or {}
    message = state["message"]
    parts = [
        f"사용자: {state.get('user_nickname', '로그인 사용자')}",
        f"현재 화면: {context.get('path') or '알 수 없음'}",
    ]
    if context.get("post_id"):
        parts.append(f"게시글 ID: {context['post_id']}")
    if context.get("post_title"):
        parts.append(f"게시글 제목: {context['post_title']}")
    if context.get("post_summary"):
        parts.append(f"게시글 검색 요약: {context['post_summary']}")
    parts.append(f"사용자 질문: {message}")

    return {
        "goal": "역사 커뮤니티 챗봇 답변",
        "topic": "\n".join(parts),
    }


def _run_retrieval_agent_node(
    state: ChatAgentState,
    db: Session,
    settings: Settings,
) -> ChatAgentState:
    response = run_agent(db, settings, state["goal"], state["topic"])
    if state.get("graph_mode") == "langgraph":
        graph_output = "prepare_context -> run_retrieval_agent 순서로 챗봇 요청을 처리했습니다."
    else:
        graph_output = "LangGraph 패키지가 없는 환경이라 같은 노드 순서를 로컬 fallback으로 처리했습니다."

    return {
        "response": AgentRunResponse(
            steps=[
                AgentStep(name="langgraph.chat", output=graph_output),
                *response.steps,
            ],
            final_answer=response.final_answer,
            tool_logs=response.tool_logs,
        )
    }
