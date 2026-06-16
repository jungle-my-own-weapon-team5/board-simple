"""Google Gemini generation provider adapter."""

from __future__ import annotations

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
    AIUsage,
    EmbeddingRequest,
    EmbeddingResult,
)


DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProvider):
    """Gemini generateContent 응답을 backend 공통 provider 계약으로 변환합니다."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url.strip() or DEFAULT_GEMINI_BASE_URL).rstrip("/")
        self.transport = transport

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self._require_api_key()
        if not request.model.strip():
            raise ProviderCapabilityError("Gemini text generation model is required")
        if not request.prompt.strip():
            raise ProviderCapabilityError("Gemini text generation prompt must not be empty")

        response_json = self._post_text_generation(request)
        return self._parse_text_generation_response(response_json, request)

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        raise ProviderCapabilityError("Gemini embedding is not configured in this app")

    def _post_text_generation(self, request: AITextRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.prompt}],
                }
            ]
        }
        if request.temperature is not None:
            payload["generationConfig"] = {"temperature": request.temperature}

        try:
            with httpx.Client(
                timeout=request.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{self.base_url}/models/{request.model}:generateContent",
                    headers=self._build_headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Gemini text generation request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError("Gemini text generation request failed") from exc

        self._raise_for_error_response(response)
        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "Gemini text generation response was not valid JSON"
            ) from exc
        if not isinstance(response_json, dict):
            raise ProviderResponseError(
                "Gemini text generation response must be an object"
            )
        return response_json

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _raise_for_error_response(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ProviderAuthError("Gemini authentication failed")
        if status_code == 429:
            raise ProviderRateLimitError("Gemini rate limit exceeded")
        if status_code in {408, 504}:
            raise ProviderTimeoutError("Gemini text generation request timed out")
        if status_code >= 500:
            raise ProviderUnavailableError("Gemini text generation service unavailable")
        raise ProviderResponseError("Gemini text generation request rejected")

    def _parse_text_generation_response(
        self,
        response_json: dict[str, Any],
        request: AITextRequest,
    ) -> AITextResult:
        candidates = response_json.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderResponseError("Gemini response candidates must be a non-empty list")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ProviderResponseError("Gemini response candidate must be an object")

        text = _extract_candidate_text(candidate)
        if not text:
            raise ProviderResponseError("Gemini response text was empty")

        finish_reason = candidate.get("finishReason")
        response_model = response_json.get("modelVersion")
        return AITextResult(
            text=text,
            agent_provider=self.provider_name,
            agent_model_name=response_model if isinstance(response_model, str) else request.model,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            usage=_parse_usage(response_json.get("usageMetadata")),
            raw_response_id=None,
        )

    def _require_api_key(self) -> None:
        if not self.api_key.strip():
            raise ProviderConfigError("GEMINI_API_KEY is required")


def _extract_candidate_text(candidate: dict[str, Any]) -> str:
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ProviderResponseError("Gemini response content must be an object")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ProviderResponseError("Gemini response content parts must be a list")

    text_parts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
    return "".join(text_parts)


def _parse_usage(value: object) -> AIUsage | None:
    if not isinstance(value, dict):
        return None
    input_tokens = value.get("promptTokenCount")
    output_tokens = value.get("candidatesTokenCount")
    total_tokens = value.get("totalTokenCount")
    return AIUsage(
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        total_tokens=total_tokens if isinstance(total_tokens, int) else None,
    )
