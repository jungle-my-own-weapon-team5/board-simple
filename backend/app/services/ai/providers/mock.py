"""테스트용 mock AI provider입니다."""
from app.services.ai.errors import ProviderCapabilityError
from app.services.ai.providers.base import AIProvider
from app.services.ai.types import (
    AITextRequest,
    AITextResult,
    EmbeddingRequest,
    EmbeddingResult,
)


class MockProvider(AIProvider):
    """테스트에서 실제 외부 AI API 호출을 대체하는 provider입니다."""

    provider_name = "mock"

    def generate_text(self, request: AITextRequest) -> AITextResult:
        # 테스트 재현성을 위해 입력 prompt를 그대로 확장하지 않고 고정된 응답을 반환합니다.
        return AITextResult(
            text="Mock provider response",
            agent_provider=self.provider_name,
            agent_model_name=request.model,
            finish_reason="stop",
            raw_response_id="mock-response-id",
        )

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        if request.dimensions <= 0:
            raise ProviderCapabilityError("mock embedding dimensions must be positive")

        return [
            EmbeddingResult(
                embedding=self._build_embedding(text, request.dimensions),
                embedding_provider=self.provider_name,
                embedding_model_name=request.model,
                dimensions=request.dimensions,
                input_index=index,
            )
            for index, text in enumerate(request.texts)
        ]

    def _build_embedding(self, text: str, dimensions: int) -> list[float]:
        # 같은 입력 text는 항상 같은 vector가 되도록 간단한 deterministic 값을 만듭니다.
        seed = sum(text.encode("utf-8"))
        return [((seed + index) % 100) / 100 for index in range(dimensions)]