# 이 파일은 OpenAI SDK를 바로 route나 RAG service에서 호출하지 않도록 막는 경계입니다.
from app.services.ai.errors import ProviderCapabilityError, ProviderConfigError
from app.services.ai.providers.base import AIProvider
from app.services.ai.types import (
    AITextRequest,
    AITextResult,
    EmbeddingRequest,
    EmbeddingResult,
)


class OpenAIProvider(AIProvider):
    """OpenAI API 호출을 담당할 provider adapter 골격입니다."""

    provider_name = "openai"

    def __init__(self, api_key: str, base_url: str = "") -> None:
        self.api_key = api_key
        self.base_url = base_url

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self._require_api_key()

        # 실제 OpenAI 호출은 다음 단계에서 SDK 또는 HTTP client 정책을 확정한 뒤 구현합니다.
        raise ProviderCapabilityError("OpenAI text generation is not implemented yet")

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        self._require_api_key()
        if request.dimensions <= 0:
            raise ProviderCapabilityError("OpenAI embedding dimensions must be positive")

        # 실제 OpenAI 호출은 다음 단계에서 SDK 또는 HTTP client 정책을 확정한 뒤 구현합니다.
        raise ProviderCapabilityError("OpenAI embeddings are not implemented yet")

    def _require_api_key(self) -> None:
        if not self.api_key.strip():
            raise ProviderConfigError("OPENAI_API_KEY is required")