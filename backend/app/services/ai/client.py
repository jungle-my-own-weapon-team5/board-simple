from app.core.config import Settings
from app.services.ai.errors import ProviderConfigError
from app.services.ai.providers.base import AIProvider
from app.services.ai.providers.mock import MockProvider
from app.services.ai.providers.openai import OpenAIProvider
from app.services.ai.types import AITextRequest, AITextResult, EmbeddingRequest, EmbeddingResult


class AIClient:
    """설정값에 따라 generation provider와 embedding provider를 선택하는 얇은 client입니다."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_text(self, request: AITextRequest) -> AITextResult:
        provider = self._build_agent_provider()
        return provider.generate_text(request)

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        provider = self._build_embedding_provider()
        return provider.embed_texts(request)

    def _build_agent_provider(self) -> AIProvider:
        if self.settings.ai_agent_provider == "mock":
            return MockProvider()
        if self.settings.ai_agent_provider == "openai":
            return OpenAIProvider(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )

        raise ProviderConfigError(
            f"Unsupported AI_AGENT_PROVIDER: {self.settings.ai_agent_provider}"
        )

    def _build_embedding_provider(self) -> AIProvider:
        if self.settings.ai_embedding_provider == "mock":
            return MockProvider()
        if self.settings.ai_embedding_provider == "openai":
            return OpenAIProvider(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )

        raise ProviderConfigError(
            f"Unsupported AI_EMBEDDING_PROVIDER: {self.settings.ai_embedding_provider}"
        )