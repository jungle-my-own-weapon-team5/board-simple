from functools import lru_cache
from pathlib import Path

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://board:board@localhost:5432/board"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    frontend_origin: AnyUrl = "http://localhost:3000"
    auth_cookie_secure: bool = False
    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536
    openai_strategy_agent_model: str = "gpt-5.4-mini"
    openai_fallback_model: str = "gpt-5.4-mini"
    upload_dir: str = "uploads"
    food_classifier_model_path: str = "app/services/resnet34_food_fc_only.pt"
    food_classifier_device: str = "auto"
    food_classifier_top_k: int = 3
    food_classifier_auto_accept_threshold: float = 0.8
    food_classifier_user_confirm_threshold: float = 0.5

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE,),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
