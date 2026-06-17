from pydantic import ValidationError

from app.mcp.tools import create_post
from app.models.user import User
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentCreatedPost,
    AgentPendingAction,
    AgentSource,
)
from app.services.agent.errors import AgentGenerationError, AgentNotConfiguredError
from app.services.agent.executor import execute_action
from app.services.agent.planner import select_action
from app.services.agent.presenter import (
    answer_with_rag,
    answer_with_tool_result,
    dump_model,
    sources_from_rag_answer,
    sources_from_result,
)
from app.services.agent.workflows import (
    execute_post_workflow,
    message_with_context,
    pending_action_tags,
)
from app.services.rag import RagGenerationError, RagNotConfiguredError


def chat_with_agent(payload: AgentChatRequest, current_user: User) -> AgentChatResponse:
    if payload.confirm_action is not None:
        action = payload.confirm_action
        if action.type == "apply_post_draft":
            return AgentChatResponse(answer="작성/수정 페이지에서 초안을 적용할 수 있습니다.")

        post = create_post(
            title=action.title,
            content=action.content,
            author_email=current_user.email,
        )
        return AgentChatResponse(
            answer=f"게시글을 생성했습니다: {post.title}",
            sources=[AgentSource(post_id=post.id, title=post.title, snippet=post.content[:160])],
            created_post=AgentCreatedPost(post_id=post.id, title=post.title),
        )

    plan = select_action(message_with_context(payload))
    if plan.action == "prepare_create_post":
        try:
            pending_action = AgentPendingAction(
                type="create_post",
                title=str(plan.args.get("title", "")).strip(),
                content=str(plan.args.get("content", "")).strip(),
                tags=pending_action_tags(plan.args.get("tags", [])),
            )
        except ValidationError as exc:
            raise AgentGenerationError("Failed to prepare a post creation action") from exc
        return AgentChatResponse(
            answer="이 내용으로 게시글을 생성할까요?",
            pending_action=pending_action,
        )

    if plan.action == "prepare_post_draft":
        try:
            pending_action = AgentPendingAction(
                type="apply_post_draft",
                title=str(plan.args.get("title", "")).strip(),
                content=str(plan.args.get("content", "")).strip(),
                tags=pending_action_tags(plan.args.get("tags", [])),
            )
        except ValidationError as exc:
            raise AgentGenerationError("Failed to prepare a post draft action") from exc
        return AgentChatResponse(
            answer="이 초안을 작성/수정 폼에 적용할까요?",
            pending_action=pending_action,
        )

    if plan.action == "plan_post_workflow":
        try:
            return execute_post_workflow(plan, payload.context)
        except ValidationError as exc:
            raise AgentGenerationError("Failed to prepare a post workflow action") from exc

    if plan.action == "answer_direct":
        return AgentChatResponse(answer=plan.answer or "게시판에서 수행할 작업을 조금 더 구체적으로 알려주세요.")

    if plan.action == "rag_search":
        question = str(plan.args.get("question") or plan.args.get("q") or payload.message).strip()
        if not question:
            raise ValueError("question must not be empty")
        try:
            rag_result = answer_with_rag(question)
        except RagNotConfiguredError as exc:
            raise AgentNotConfiguredError("RAG is not configured") from exc
        except RagGenerationError as exc:
            raise AgentGenerationError("Failed to generate a RAG answer") from exc
        return AgentChatResponse(
            answer=rag_result.answer,
            sources=sources_from_rag_answer(rag_result),
        )

    result = execute_action(plan)
    dumped_result = dump_model(result)
    return AgentChatResponse(
        answer=answer_with_tool_result(payload.message, plan.action, dumped_result),
        sources=sources_from_result(plan.action, result),
    )
