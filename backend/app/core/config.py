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
    openai_chat_model: str = "gpt-5.5"
    openai_embedding_model: str = "text-embedding-3-large"
    news_llm_debug: bool = False
    rag_enabled: bool = False
    rag_collection_name: str = "tech_news_posts"
    rag_top_k: int = 5

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE,),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
