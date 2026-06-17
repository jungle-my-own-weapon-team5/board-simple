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
    openai_llm_model: str = "gpt-5.4-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_image_model: str = "gpt-image-1"
    openai_thumbnail_size: str = "1536x1024"
    redis_url: str | None = None
    rag_cache_ttl_seconds: int = 600
    thumbnail_cache_ttl_seconds: int = 3600
    post_list_cache_ttl_seconds: int = 10
    admin_email: str = "admin@example.com"
    admin_nickname: str = "관리자"
    national_library_api_key: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    brave_search_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE,),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
