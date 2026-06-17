import json

from openai import OpenAIError
from pydantic import ValidationError

from app.core.config import get_settings
from app.services.agent.errors import AgentGenerationError
from app.services.agent.models import AgentActionPlan
from app.services.agent.openai_client import get_openai_client, strip_json_fence


def select_action(message: str) -> AgentActionPlan:
    settings = get_settings()
    client = get_openai_client(settings)
    instructions = (
        "You are an AI agent for a board app. Choose exactly one action and return only JSON. "
        "Allowed actions: rag_search, search_posts, get_recent_posts, get_post, get_comments, "
        "get_post_with_comments, list_tags, prepare_create_post, prepare_post_draft, "
        "plan_post_workflow, answer_direct. "
        "Use rag_search for semantic questions about post contents. "
        "The server MCP tools are search_posts, get_recent_posts, get_post, get_comments, "
        "get_post_with_comments, list_tags, and prepare_create_post. "
        "Use search_posts only for title keyword search. "
        "Use prepare_create_post only when the user wants to write a new post. "
        "Use plan_post_workflow when the user gives a writing goal and expects an agent to "
        "search existing posts, check duplicates, prepare a draft, and ask before applying. "
        "Use prepare_post_draft when the user asks for a body draft, post draft, Markdown draft, "
        "or a draft to insert into the editor. Generate a title, Markdown content, and tags. "
        "Do not execute destructive actions. JSON shape: "
        '{"action":"search_posts","args":{"q":"keyword","page":1,"size":10},"answer":null}. '
        'For rag_search, use {"action":"rag_search","args":{"question":"question"},"answer":null}. '
        "For prepare_create_post, args must contain title and content, and may contain tags. "
        "For prepare_post_draft, args must contain title, content, and tags. "
        "For plan_post_workflow, args must contain search_query, title, content, and tags. "
        "For answer_direct, put the answer in answer."
    )
    try:
        response = client.responses.create(
            model=settings.openai_chat_model,
            instructions=instructions,
            input=message,
            store=False,
        )
        payload = json.loads(strip_json_fence(response.output_text))
        return AgentActionPlan.model_validate(payload)
    except (OpenAIError, json.JSONDecodeError, ValidationError) as exc:
        raise AgentGenerationError("Failed to choose an agent action") from exc
