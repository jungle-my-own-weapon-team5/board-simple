from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
DEFAULT_JWT_SECRET_KEY = "change-me"


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://board:board@localhost:5432/board"
    jwt_secret_key: str = DEFAULT_JWT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    frontend_origin: AnyUrl = "http://localhost:3000"
    auth_cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE,),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.app_env != "production":
            return self

        errors: list[str] = []
        frontend_origin = str(self.frontend_origin).rstrip("/")
        if self.jwt_secret_key == DEFAULT_JWT_SECRET_KEY:
            errors.append("JWT_SECRET_KEY must be changed in production")
        if not self.auth_cookie_secure:
            errors.append("AUTH_COOKIE_SECURE must be true in production")
        if self.frontend_origin.scheme != "https":
            errors.append("FRONTEND_ORIGIN must use https in production")
        if self.frontend_origin.host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            errors.append("FRONTEND_ORIGIN must not be localhost in production")
        if frontend_origin.endswith(".localhost"):
            errors.append("FRONTEND_ORIGIN must not be a localhost domain in production")
        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
