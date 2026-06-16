"""Anthropic Claude generation provider adapter."""

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


DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(AIProvider):
    """Claude Messages API 응답을 backend 공통 provider 계약으로 변환합니다."""

    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url.strip() or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
        self.transport = transport

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self._require_api_key()
        if not request.model.strip():
            raise ProviderCapabilityError("Anthropic text generation model is required")
        if not request.prompt.strip():
            raise ProviderCapabilityError(
                "Anthropic text generation prompt must not be empty"
            )

        response_json = self._post_text_generation(request)
        return self._parse_text_generation_response(response_json, request)

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        raise ProviderCapabilityError("Anthropic embedding is not configured in this app")

    def _post_text_generation(self, request: AITextRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": request.prompt,
                }
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        try:
            with httpx.Client(
                timeout=request.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{self.base_url}/messages",
                    headers=self._build_headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Anthropic text generation request timed out"
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                "Anthropic text generation request failed"
            ) from exc

        self._raise_for_error_response(response)
        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "Anthropic text generation response was not valid JSON"
            ) from exc
        if not isinstance(response_json, dict):
            raise ProviderResponseError(
                "Anthropic text generation response must be an object"
            )
        return response_json

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }

    def _raise_for_error_response(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ProviderAuthError("Anthropic authentication failed")
        if status_code == 429:
            raise ProviderRateLimitError("Anthropic rate limit exceeded")
        if status_code in {408, 504}:
            raise ProviderTimeoutError("Anthropic text generation request timed out")
        if status_code >= 500:
            raise ProviderUnavailableError(
                "Anthropic text generation service unavailable"
            )
        raise ProviderResponseError("Anthropic text generation request rejected")

    def _parse_text_generation_response(
        self,
        response_json: dict[str, Any],
        request: AITextRequest,
    ) -> AITextResult:
        text = _extract_text(response_json.get("content"))
        if not text:
            raise ProviderResponseError("Anthropic response text was empty")

        response_model = response_json.get("model")
        stop_reason = response_json.get("stop_reason")
        response_id = response_json.get("id")
        return AITextResult(
            text=text,
            agent_provider=self.provider_name,
            agent_model_name=response_model
            if isinstance(response_model, str)
            else request.model,
            finish_reason=stop_reason if isinstance(stop_reason, str) else None,
            usage=_parse_usage(response_json.get("usage")),
            raw_response_id=response_id if isinstance(response_id, str) else None,
        )

    def _require_api_key(self) -> None:
        if not self.api_key.strip():
            raise ProviderConfigError("ANTHROPIC_API_KEY is required")


def _extract_text(value: object) -> str:
    if not isinstance(value, list):
        raise ProviderResponseError("Anthropic response content must be a list")

    text_parts: list[str] = []
    for block in value:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
    return "".join(text_parts)


def _parse_usage(value: object) -> AIUsage | None:
    if not isinstance(value, dict):
        return None
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    total_tokens = None
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    return AIUsage(
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        total_tokens=total_tokens,
    )
