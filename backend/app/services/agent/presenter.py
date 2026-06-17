import json
from typing import Any

from openai import OpenAIError
from pydantic import BaseModel

from app.core.config import get_settings
from app.mcp.tools import session_scope
from app.schemas.agent import AgentSource
from app.services.agent.errors import AgentGenerationError
from app.services.agent.openai_client import get_openai_client
from app.services.rag import RagAnswer, answer_question


def answer_with_tool_result(
    message: str,
    action: str,
    tool_result: Any,
) -> str:
    settings = get_settings()
    client = get_openai_client(settings)
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


def dump_model(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [dump_model(item) for item in value]
    return value


def snippet(content: str, limit: int = 160) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def sources_from_result(action: str, result: Any) -> list[AgentSource]:
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
        return [AgentSource(post_id=result.id, title=result.title, snippet=snippet(result.content))]
    if action == "get_post_with_comments":
        return [
            AgentSource(
                post_id=result.post.id,
                title=result.post.title,
                snippet=snippet(result.post.content),
            )
        ]
    return []


def answer_with_rag(question: str) -> RagAnswer:
    with session_scope() as db:
        return answer_question(db, question)


def sources_from_rag_answer(result: RagAnswer) -> list[AgentSource]:
    return [
        AgentSource(
            post_id=source.post_id,
            title=source.title,
            heading=source.heading,
            anchor=source.anchor,
            snippet=source.snippet,
        )
        for source in result.sources
    ]
