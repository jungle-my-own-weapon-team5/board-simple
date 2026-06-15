# 이 파일은 OpenAI SDK/API를 바로 route나 RAG service에서 호출하지 않도록 막는 경계입니다.
import json
from typing import Any

import httpx2 as httpx

from app.services.ai.errors import (
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderConfigError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.services.ai.providers.base import AIProvider
from app.services.ai.types import (
    AITextRequest,
    AITextResult,
    EmbeddingRequest,
    EmbeddingResult,
)


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(AIProvider):
    """OpenAI API 호출을 backend 공통 provider 계약에 맞게 변환합니다."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url.strip() or DEFAULT_OPENAI_BASE_URL).rstrip("/")
        # 테스트에서는 MockTransport를 주입해 실제 OpenAI 네트워크 호출 없이 검증합니다.
        self.transport = transport

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self._require_api_key()

        # 실제 OpenAI 호출은 다음 단계에서 SDK 또는 HTTP client 정책을 확정한 뒤 구현합니다.
        raise ProviderCapabilityError("OpenAI text generation is not implemented yet")

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        self._require_api_key()
        if request.dimensions <= 0:
            raise ProviderCapabilityError("OpenAI embedding dimensions must be positive")
        if not request.texts:
            return []
        if any(text == "" for text in request.texts):
            raise ProviderCapabilityError("OpenAI embedding input text must not be empty")

        response_json = self._post_embeddings(request)
        results = self._parse_embedding_response(response_json, request)
        return sorted(results, key=lambda result: result.input_index)

    def _post_embeddings(self, request: EmbeddingRequest) -> dict[str, Any]:
        payload = {
            "input": request.texts,
            "model": request.model,
            "dimensions": request.dimensions,
            "encoding_format": "float",
        }
        try:
            with httpx.Client(
                timeout=request.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._build_headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("OpenAI embedding request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError("OpenAI embedding request failed") from exc

        self._raise_for_error_response(response)
        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "OpenAI embedding response was not valid JSON"
            ) from exc
        if not isinstance(response_json, dict):
            raise ProviderResponseError("OpenAI embedding response must be an object")
        return response_json

    def _build_headers(self) -> dict[str, str]:
        # Authorization 값은 로그나 예외 메시지에 포함하지 않습니다.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _raise_for_error_response(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ProviderAuthError("OpenAI authentication failed")
        if status_code == 429:
            raise ProviderRateLimitError("OpenAI rate limit exceeded")
        if status_code in {408, 504}:
            raise ProviderTimeoutError("OpenAI embedding request timed out")
        if status_code >= 500:
            raise ProviderUnavailableError("OpenAI embedding service unavailable")
        raise ProviderResponseError("OpenAI embedding request rejected")

    def _parse_embedding_response(
        self,
        response_json: dict[str, Any],
        request: EmbeddingRequest,
    ) -> list[EmbeddingResult]:
        data = response_json.get("data")
        if not isinstance(data, list):
            raise ProviderResponseError("OpenAI embedding response data must be a list")
        if len(data) != len(request.texts):
            raise ProviderResponseError("OpenAI embedding response count mismatch")

        response_model = response_json.get("model")
        model_name = response_model if isinstance(response_model, str) else request.model
        return [
            self._parse_embedding_item(item, model_name=model_name)
            for item in data
        ]

    def _parse_embedding_item(
        self,
        item: object,
        model_name: str,
    ) -> EmbeddingResult:
        if not isinstance(item, dict):
            raise ProviderResponseError("OpenAI embedding item must be an object")

        embedding = item.get("embedding")
        input_index = item.get("index")
        if not isinstance(embedding, list):
            raise ProviderResponseError("OpenAI embedding vector must be a list")
        if not isinstance(input_index, int):
            raise ProviderResponseError("OpenAI embedding index must be an integer")
        if not all(self._is_embedding_number(value) for value in embedding):
            raise ProviderResponseError("OpenAI embedding vector must contain numbers")

        vector = [float(value) for value in embedding]
        return EmbeddingResult(
            embedding=vector,
            embedding_provider=self.provider_name,
            embedding_model_name=model_name,
            dimensions=len(vector),
            input_index=input_index,
        )

    def _is_embedding_number(self, value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _require_api_key(self) -> None:
        if not self.api_key.strip():
            raise ProviderConfigError("OPENAI_API_KEY is required")
