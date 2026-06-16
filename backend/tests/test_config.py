import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


def test_development_settings_allow_local_defaults() -> None:
    settings = Settings(app_env="development")

    assert settings.app_env == "development"


def test_law_open_api_url_settings_have_defaults() -> None:
    settings = Settings(app_env="development")

    assert settings.law_open_api_base_url == "https://www.law.go.kr/DRF/lawSearch.do"
    assert (
        settings.law_open_api_service_url
        == "https://www.law.go.kr/DRF/lawService.do"
    )


def test_ai_rag_disabled_allows_empty_provider_settings() -> None:
    settings = Settings(
        ai_rag_enabled=False,
        openai_api_key="",
        ai_agent_model="",
        ai_embedding_model="",
        ai_embedding_dimensions="",
    )

    assert settings.ai_rag_enabled is False
    assert settings.ai_embedding_dimensions is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"openai_api_key": ""}, "OPENAI_API_KEY"),
        ({"ai_agent_model": ""}, "AI_AGENT_MODEL"),
        ({"ai_embedding_model": ""}, "AI_EMBEDDING_MODEL"),
        ({"ai_embedding_dimensions": None}, "AI_EMBEDDING_DIMENSIONS"),
        ({"ai_embedding_dimensions": 0}, "AI_EMBEDDING_DIMENSIONS"),
    ],
)
def test_ai_rag_enabled_requires_openai_settings(
    overrides: dict[str, object], message: str
) -> None:
    values = {
        "ai_rag_enabled": True,
        "ai_agent_provider": "openai",
        "ai_embedding_provider": "openai",
        "openai_api_key": "present",
        "ai_agent_model": "gpt-test",
        "ai_embedding_model": "embedding-test",
        "ai_embedding_dimensions": 1536,
        **overrides,
    }

    with pytest.raises(ValidationError, match=message):
        Settings(**values)


def test_ai_rag_validation_error_does_not_include_secret_values() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ai_rag_enabled=True,
            ai_agent_provider="openai",
            ai_embedding_provider="openai",
            openai_api_key="present-but-redacted",
            ai_agent_model="",
            ai_embedding_model="embedding-test",
            ai_embedding_dimensions=1536,
        )

    message = str(exc_info.value)
    assert "AI_AGENT_MODEL" in message
    assert "present-but-redacted" not in message


def test_mcp_enabled_requires_allowed_tools() -> None:
    with pytest.raises(ValidationError, match="MCP_ALLOWED_TOOLS"):
        Settings(mcp_server_enabled=True, mcp_allowed_tools="")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ai_agent_max_repeated_actions": 0}, "AI_AGENT_MAX_REPEATED_ACTIONS"),
        ({"ai_agent_max_handoffs": 0}, "AI_AGENT_MAX_HANDOFFS"),
        (
            {"ai_agent_max_external_sync_candidates": 0},
            "AI_AGENT_MAX_EXTERNAL_SYNC_CANDIDATES",
        ),
    ],
)
def test_agent_loop_guard_settings_must_be_positive(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"jwt_secret_key": "change-me"}, "JWT_SECRET_KEY"),
        ({"auth_cookie_secure": False}, "AUTH_COOKIE_SECURE"),
        ({"frontend_origin": "http://example.com"}, "FRONTEND_ORIGIN"),
        ({"frontend_origin": "https://localhost:3000"}, "FRONTEND_ORIGIN"),
    ],
)
def test_production_settings_reject_insecure_values(
    overrides: dict[str, object], message: str
) -> None:
    values = {
        "app_env": "production",
        "jwt_secret_key": "production-secret",
        "auth_cookie_secure": True,
        "frontend_origin": "https://example.com",
        **overrides,
    }

    with pytest.raises(ValidationError, match=message):
        Settings(**values)


def test_production_settings_accept_secure_values() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="production-secret",
        auth_cookie_secure=True,
        frontend_origin="https://example.com",
    )

    assert settings.app_env == "production"


def test_development_app_keeps_openapi_docs_enabled() -> None:
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"
