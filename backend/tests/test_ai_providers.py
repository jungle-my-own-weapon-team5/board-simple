import json

import httpx2 as httpx
import pytest

from app.core.config import Settings
from app.services.ai.client import AIClient
from app.services.ai.errors import (
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderConfigError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.services.ai.providers.openai import OpenAIProvider
from app.services.ai.types import AITextRequest, EmbeddingRequest


def test_mock_provider_generates_text() -> None:
    settings = Settings(
        ai_agent_provider="mock",
        ai_agent_model="mock-chat",
    )
    client = AIClient(settings)

    result = client.generate_text(
        AITextRequest(
            prompt="테스트 프롬프트",
            model=settings.ai_agent_model,
            temperature=None,
            timeout_seconds=settings.ai_request_timeout_seconds,
            metadata={"test": "true"},
        )
    )

    assert result.text
    assert result.agent_provider == "mock"
    assert result.agent_model_name == "mock-chat"


def test_mock_provider_embeds_texts_with_requested_dimensions() -> None:
    settings = Settings(
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=8,
    )
    client = AIClient(settings)

    results = client.embed_texts(
        EmbeddingRequest(
            texts=["첫 번째 문장", "두 번째 문장"],
            model=settings.ai_embedding_model,
            dimensions=settings.ai_embedding_dimensions,
            timeout_seconds=settings.ai_request_timeout_seconds,
            metadata={"test": "true"},
        )
    )

    assert len(results) == 2
    assert results[0].embedding_provider == "mock"
    assert results[0].embedding_model_name == "mock-embedding"
    assert results[0].dimensions == 8
    assert len(results[0].embedding) == 8
    assert results[0].input_index == 0
    assert results[1].input_index == 1


def test_openai_provider_requires_api_key_for_generation() -> None:
    settings = Settings(
        ai_agent_provider="openai",
        ai_agent_model="gpt-test",
        openai_api_key="",
    )
    client = AIClient(settings)

    with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"):
        client.generate_text(
            AITextRequest(
                prompt="테스트",
                model=settings.ai_agent_model,
                temperature=None,
                timeout_seconds=settings.ai_request_timeout_seconds,
                metadata={},
            )
        )


def test_openai_provider_requires_api_key_for_embedding() -> None:
    settings = Settings(
        ai_embedding_provider="openai",
        ai_embedding_model="embedding-test",
        ai_embedding_dimensions=8,
        openai_api_key="",
    )
    client = AIClient(settings)

    with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"):
        client.embed_texts(
            EmbeddingRequest(
                texts=["테스트"],
                model=settings.ai_embedding_model,
                dimensions=settings.ai_embedding_dimensions,
                timeout_seconds=settings.ai_request_timeout_seconds,
                metadata={},
            )
        )


def test_generation_provider_without_embedding_support_fails_explicitly() -> None:
    settings = Settings(
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=8,
    )
    client = AIClient(settings)

    # embedding provider는 mock이므로 성공해야 합니다.
    client.embed_texts(
        EmbeddingRequest(
            texts=["테스트"],
            model=settings.ai_embedding_model,
            dimensions=settings.ai_embedding_dimensions,
            timeout_seconds=settings.ai_request_timeout_seconds,
            metadata={},
        )
    )

    unsupported_settings = Settings(
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=0,
    )
    unsupported_client = AIClient(unsupported_settings)

    with pytest.raises(ProviderCapabilityError, match="dimensions"):
        unsupported_client.embed_texts(
            EmbeddingRequest(
                texts=["테스트"],
                model="mock-embedding",
                dimensions=0,
                timeout_seconds=60,
                metadata={},
            )
        )


def test_openai_provider_posts_text_generation_request_and_normalizes_output_text() -> None:
    captured_requests: list[httpx.Request] = []
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "id": "resp-test",
                "model": "gpt-5.4-mini",
                "status": "completed",
                "output_text": "법률 쟁점 초안입니다.",
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 8,
                    "total_tokens": 20,
                },
            },
        )

    provider = OpenAIProvider(
        api_key="test-api-key",
        base_url="https://api.openai.test/v1/",
        transport=httpx.MockTransport(handler),
    )

    result = provider.generate_text(
        AITextRequest(
            prompt="보증금 반환 쟁점을 정리해주세요.",
            model="gpt-5.4-mini",
            temperature=0.2,
            timeout_seconds=10,
            metadata={"purpose": "agent_draft"},
        )
    )

    assert len(captured_requests) == 1
    assert str(captured_requests[0].url) == "https://api.openai.test/v1/responses"
    assert captured_requests[0].headers["Authorization"].startswith("Bearer ")
    assert captured_payloads == [
        {
            "model": "gpt-5.4-mini",
            "input": "보증금 반환 쟁점을 정리해주세요.",
            "temperature": 0.2,
        }
    ]
    assert result.text == "법률 쟁점 초안입니다."
    assert result.agent_provider == "openai"
    assert result.agent_model_name == "gpt-5.4-mini"
    assert result.finish_reason == "completed"
    assert result.raw_response_id == "resp-test"
    assert result.usage is not None
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 8
    assert result.usage.total_tokens == 20


def test_openai_provider_parses_text_generation_output_array() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp-array",
                "model": "gpt-array",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "첫 번째 문장."},
                            {"type": "output_text", "text": " 두 번째 문장."},
                        ],
                    }
                ],
            },
        )

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    result = provider.generate_text(_openai_text_request(model="gpt-array"))

    assert result.text == "첫 번째 문장. 두 번째 문장."
    assert result.agent_model_name == "gpt-array"


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
    ],
)
def test_openai_provider_maps_generation_http_errors_to_provider_errors(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": "must not leak test-api-key"}},
        )

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(expected_error) as exc_info:
        provider.generate_text(_openai_text_request())

    assert "test-api-key" not in str(exc_info.value)


def test_openai_provider_maps_generation_timeout_to_provider_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout with test-api-key", request=request)

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTimeoutError, match="timed out") as exc_info:
        provider.generate_text(_openai_text_request())

    assert "test-api-key" not in str(exc_info.value)


@pytest.mark.parametrize(
    "response_json",
    [
        {"id": "resp-no-text", "model": "gpt-test"},
        {"id": "resp-empty-text", "model": "gpt-test", "output_text": ""},
        {"id": "resp-invalid-output", "model": "gpt-test", "output": "bad"},
    ],
)
def test_openai_provider_rejects_invalid_text_generation_response_shape(
    response_json: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderResponseError):
        provider.generate_text(_openai_text_request())


def test_openai_provider_posts_embedding_request_and_normalizes_response() -> None:
    captured_requests: list[httpx.Request] = []
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [
                    {
                        "object": "embedding",
                        "index": 1,
                        "embedding": [0.3, 0.4, 0.5],
                    },
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": [0.0, 0.1, 0.2],
                    },
                ],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            },
        )

    provider = OpenAIProvider(
        api_key="test-api-key",
        base_url="https://api.openai.test/v1/",
        transport=httpx.MockTransport(handler),
    )

    results = provider.embed_texts(
        EmbeddingRequest(
            texts=["첫 번째 문장", "두 번째 문장"],
            model="text-embedding-3-small",
            dimensions=3,
            timeout_seconds=10,
            metadata={},
        )
    )

    assert len(captured_requests) == 1
    assert str(captured_requests[0].url) == "https://api.openai.test/v1/embeddings"
    assert captured_requests[0].headers["Authorization"].startswith("Bearer ")
    assert captured_payloads == [
        {
            "input": ["첫 번째 문장", "두 번째 문장"],
            "model": "text-embedding-3-small",
            "dimensions": 3,
            "encoding_format": "float",
        }
    ]
    assert [result.input_index for result in results] == [0, 1]
    assert [result.embedding for result in results] == [
        [0.0, 0.1, 0.2],
        [0.3, 0.4, 0.5],
    ]
    assert [result.dimensions for result in results] == [3, 3]
    assert {result.embedding_provider for result in results} == {"openai"}
    assert {result.embedding_model_name for result in results} == {
        "text-embedding-3-small"
    }


def test_openai_provider_skips_http_call_for_empty_text_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("empty text list must not call OpenAI")

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    results = provider.embed_texts(
        EmbeddingRequest(
            texts=[],
            model="text-embedding-3-small",
            dimensions=3,
            timeout_seconds=10,
            metadata={},
        )
    )

    assert results == []


def test_openai_provider_rejects_empty_embedding_input_text() -> None:
    provider = OpenAIProvider(api_key="test-api-key")

    with pytest.raises(ProviderCapabilityError, match="input text"):
        provider.embed_texts(
            EmbeddingRequest(
                texts=[""],
                model="text-embedding-3-small",
                dimensions=3,
                timeout_seconds=10,
                metadata={},
            )
        )


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
    ],
)
def test_openai_provider_maps_http_errors_to_provider_errors(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "redacted"}})

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(expected_error):
        provider.embed_texts(_openai_embedding_request())


def test_openai_provider_maps_timeout_to_provider_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTimeoutError, match="timed out"):
        provider.embed_texts(_openai_embedding_request())


def test_openai_provider_rejects_malformed_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderResponseError, match="valid JSON"):
        provider.embed_texts(_openai_embedding_request())


@pytest.mark.parametrize(
    "response_json",
    [
        {"model": "text-embedding-3-small"},
        {"data": []},
        {"data": [{"index": 0, "embedding": "not-a-vector"}]},
        {"data": [{"index": "0", "embedding": [0.1, 0.2, 0.3]}]},
        {"data": [{"index": 0, "embedding": [0.1, "bad", 0.3]}]},
        {"data": [{"index": 0, "embedding": [0.1, True, 0.3]}]},
    ],
)
def test_openai_provider_rejects_invalid_embedding_response_shape(
    response_json: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    provider = OpenAIProvider(
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderResponseError):
        provider.embed_texts(_openai_embedding_request())


def _openai_embedding_request() -> EmbeddingRequest:
    return EmbeddingRequest(
        texts=["테스트 문장"],
        model="text-embedding-3-small",
        dimensions=3,
        timeout_seconds=10,
        metadata={},
    )


def _openai_text_request(model: str = "gpt-test") -> AITextRequest:
    return AITextRequest(
        prompt="테스트 프롬프트",
        model=model,
        temperature=None,
        timeout_seconds=10,
        metadata={},
    )
