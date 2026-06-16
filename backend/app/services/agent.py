import json
from typing import Any, Literal

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings, get_settings
from app.mcp.tools import (
    create_post,
    get_comments,
    get_post,
    get_post_with_comments,
    get_recent_posts,
    list_tags,
    search_posts,
)
from app.models.user import User
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentCreatedPost,
    AgentPendingAction,
    AgentSource,
)

AgentActionName = Literal[
    "search_posts",
    "get_recent_posts",
    "get_post",
    "get_comments",
    "get_post_with_comments",
    "list_tags",
    "prepare_create_post",
    "answer_direct",
]


class AgentNotConfiguredError(Exception):
    pass


class AgentGenerationError(Exception):
    pass


class AgentActionPlan(BaseModel):
    action: AgentActionName
    args: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = None


def _get_openai_client(settings: Settings) -> OpenAI:
    if not settings.openai_api_key:
        raise AgentNotConfiguredError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json"):
        return stripped.removeprefix("```json").removesuffix("```").strip()
    if stripped.startswith("```"):
        return stripped.removeprefix("```").removesuffix("```").strip()
    return stripped


def _select_action(message: str) -> AgentActionPlan:
    settings = get_settings()
    client = _get_openai_client(settings)
    instructions = (
        "You are an AI agent for a board app. Choose exactly one action and return only JSON. "
        "Allowed actions: search_posts, get_recent_posts, get_post, get_comments, "
        "get_post_with_comments, list_tags, prepare_create_post, answer_direct. "
        "Use prepare_create_post only when the user wants to write a new post. "
        "Do not execute destructive actions. JSON shape: "
        '{"action":"search_posts","args":{"q":"keyword","page":1,"size":10},"answer":null}. '
        "For prepare_create_post, args must contain title and content. "
        "For answer_direct, put the answer in answer."
    )
    try:
        response = client.responses.create(
            model=settings.openai_chat_model,
            instructions=instructions,
            input=message,
            store=False,
        )
        payload = json.loads(_strip_json_fence(response.output_text))
        return AgentActionPlan.model_validate(payload)
    except (OpenAIError, json.JSONDecodeError, ValidationError) as exc:
        raise AgentGenerationError("Failed to choose an agent action") from exc


def _answer_with_tool_result(
    message: str,
    action: str,
    tool_result: Any,
) -> str:
    settings = get_settings()
    client = _get_openai_client(settings)
    instructions = (
        "You answer as the Board Simple AI Agent. Use only the provided tool result. "
        "Answer in the same language as the user. Keep it concise and include useful post IDs "
        "or titles when relevant."
    )
    prompt = (
        f"User message:\n{message}\n\n"
        f"Tool used: {action}\n\n"
        "Tool result JSON:\n"
        f"{json.dumps(tool_result, ensure_ascii=False)}"
    )
    try:
        response = client.responses.create(
            model=settings.openai_chat_model,
            instructions=instructions,
            input=prompt,
            store=False,
        )
        return response.output_text.strip() or "답변을 생성하지 못했습니다."
    except OpenAIError as exc:
        raise AgentGenerationError("Failed to generate an agent answer") from exc


def _dump_model(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump_model(item) for item in value]
    return value


def _snippet(content: str, limit: int = 160) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _sources_from_result(action: str, result: Any) -> list[AgentSource]:
    if action in {"search_posts"}:
        return [
            AgentSource(post_id=item.id, title=item.title, snippet=", ".join(tag.name for tag in item.tags))
            for item in result.items
        ]
    if action == "get_recent_posts":
        return [
            AgentSource(post_id=item.id, title=item.title, snippet=", ".join(tag.name for tag in item.tags))
            for item in result
        ]
    if action == "get_post":
        return [AgentSource(post_id=result.id, title=result.title, snippet=_snippet(result.content))]
    if action == "get_post_with_comments":
        return [
            AgentSource(
                post_id=result.post.id,
                title=result.post.title,
                snippet=_snippet(result.post.content),
            )
        ]
    return []


def _execute_action(plan: AgentActionPlan) -> Any:
    args = plan.args
    if plan.action == "search_posts":
        return search_posts(
            q=args.get("q"),
            page=int(args.get("page", 1)),
            size=int(args.get("size", 10)),
        )
    if plan.action == "get_recent_posts":
        return get_recent_posts(limit=int(args.get("limit", 10)))
    if plan.action == "get_post":
        return get_post(post_id=int(args["post_id"]))
    if plan.action == "get_comments":
        return get_comments(
            post_id=int(args["post_id"]),
            offset=int(args.get("offset", 0)),
            limit=int(args.get("limit", 10)),
        )
    if plan.action == "get_post_with_comments":
        return get_post_with_comments(
            post_id=int(args["post_id"]),
            comment_limit=int(args.get("comment_limit", 20)),
        )
    if plan.action == "list_tags":
        return list_tags()
    raise ValueError(f"Unsupported action: {plan.action}")


def chat_with_agent(payload: AgentChatRequest, current_user: User) -> AgentChatResponse:
    if payload.confirm_action is not None:
        action = payload.confirm_action
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

    plan = _select_action(payload.message)
    if plan.action == "prepare_create_post":
        try:
            pending_action = AgentPendingAction(
                type="create_post",
                title=str(plan.args.get("title", "")).strip(),
                content=str(plan.args.get("content", "")).strip(),
            )
        except ValidationError as exc:
            raise AgentGenerationError("Failed to prepare a post creation action") from exc
        return AgentChatResponse(
            answer="이 내용으로 게시글을 생성할까요?",
            pending_action=pending_action,
        )

    if plan.action == "answer_direct":
        return AgentChatResponse(answer=plan.answer or "게시판에서 수행할 작업을 조금 더 구체적으로 알려주세요.")

    result = _execute_action(plan)
    dumped_result = _dump_model(result)
    return AgentChatResponse(
        answer=_answer_with_tool_result(payload.message, plan.action, dumped_result),
        sources=_sources_from_result(plan.action, result),
    )
