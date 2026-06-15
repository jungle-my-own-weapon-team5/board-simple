import pytest

from app.core.config import Settings
from app.services.ai.client import AIClient
from app.services.ai.errors import ProviderCapabilityError, ProviderConfigError
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