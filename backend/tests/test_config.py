import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


def test_development_settings_allow_local_defaults() -> None:
    settings = Settings(app_env="development")

    assert settings.app_env == "development"


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
