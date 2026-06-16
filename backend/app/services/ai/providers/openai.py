# 이 파일은 OpenAI SDK/API를 바로 route나 RAG service에서 호출하지 않도록 막는 경계입니다.
import json
import ssl
from typing import Any

import httpx2 as httpx
import truststore

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
    AIUsage,
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
        verify: ssl.SSLContext | str | bool | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url.strip() or DEFAULT_OPENAI_BASE_URL).rstrip("/")
        # 테스트에서는 MockTransport를 주입해 실제 OpenAI 네트워크 호출 없이 검증합니다.
        self.transport = transport
        # Windows 개발 환경이나 보안 프록시 환경에서는 certifi bundle만으로
        # 로컬 신뢰 CA를 찾지 못할 수 있어 OS 인증서 저장소를 기본으로 사용합니다.
        self.verify = verify if verify is not None else _build_system_trust_context()

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self._require_api_key()
        if not request.model.strip():
            raise ProviderCapabilityError("OpenAI text generation model is required")
        if not request.prompt.strip():
            raise ProviderCapabilityError("OpenAI text generation prompt must not be empty")

        response_json = self._post_text_generation(request)
        return self._parse_text_generation_response(response_json, request)

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
                verify=self.verify,
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

        self._raise_for_error_response(response, operation="embedding")
        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "OpenAI embedding response was not valid JSON"
            ) from exc
        if not isinstance(response_json, dict):
            raise ProviderResponseError("OpenAI embedding response must be an object")
        return response_json

    def _post_text_generation(self, request: AITextRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "input": request.prompt,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        try:
            with httpx.Client(
                timeout=request.timeout_seconds,
                transport=self.transport,
                verify=self.verify,
            ) as client:
                response = client.post(
                    f"{self.base_url}/responses",
                    headers=self._build_headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("OpenAI text generation request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError("OpenAI text generation request failed") from exc

        self._raise_for_error_response(response, operation="text generation")
        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "OpenAI text generation response was not valid JSON"
            ) from exc
        if not isinstance(response_json, dict):
            raise ProviderResponseError(
                "OpenAI text generation response must be an object"
            )
        return response_json

    def _build_headers(self) -> dict[str, str]:
        # Authorization 값은 로그나 예외 메시지에 포함하지 않습니다.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _raise_for_error_response(self, response: httpx.Response, *, operation: str) -> None:
        status_code = response.status_code
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ProviderAuthError("OpenAI authentication failed")
        if status_code == 429:
            raise ProviderRateLimitError("OpenAI rate limit exceeded")
        if status_code in {408, 504}:
            raise ProviderTimeoutError(f"OpenAI {operation} request timed out")
        if status_code >= 500:
            raise ProviderUnavailableError(f"OpenAI {operation} service unavailable")
        raise ProviderResponseError(f"OpenAI {operation} request rejected")

    def _parse_text_generation_response(
        self,
        response_json: dict[str, Any],
        request: AITextRequest,
    ) -> AITextResult:
        text = _extract_response_text(response_json)
        if not text:
            raise ProviderResponseError(
                "OpenAI text generation response text was empty"
            )

        response_model = response_json.get("model")
        model_name = response_model if isinstance(response_model, str) else request.model
        response_id = response_json.get("id")
        status = response_json.get("status")
        return AITextResult(
            text=text,
            agent_provider=self.provider_name,
            agent_model_name=model_name,
            finish_reason=status if isinstance(status, str) else None,
            usage=_parse_usage(response_json.get("usage")),
            raw_response_id=response_id if isinstance(response_id, str) else None,
        )

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


def _extract_response_text(response_json: dict[str, Any]) -> str:
    output_text = response_json.get("output_text")
    if isinstance(output_text, str):
        return output_text

    output = response_json.get("output")
    if not isinstance(output, list):
        raise ProviderResponseError("OpenAI text generation output must be a list")

    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "".join(text_parts)


def _build_system_trust_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _parse_usage(value: object) -> AIUsage | None:
    if not isinstance(value, dict):
        return None
    return AIUsage(
        input_tokens=_optional_int(value.get("input_tokens")),
        output_tokens=_optional_int(value.get("output_tokens")),
        total_tokens=_optional_int(value.get("total_tokens")),
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
