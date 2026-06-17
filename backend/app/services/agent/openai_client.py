from openai import OpenAI

from app.core.config import Settings
from app.services.agent.errors import AgentNotConfiguredError


def get_openai_client(settings: Settings) -> OpenAI:
    if not settings.openai_api_key:
        raise AgentNotConfiguredError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json"):
        return stripped.removeprefix("```json").removesuffix("```").strip()
    if stripped.startswith("```"):
        return stripped.removeprefix("```").removesuffix("```").strip()
    return stripped
