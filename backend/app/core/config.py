from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
DEFAULT_JWT_SECRET_KEY = "change-me"
DEFAULT_MCP_ALLOWED_TOOLS = (
    "search_legal_documents,search_law_open_api,verify_citations"
)


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://board:board@localhost:5432/board"
    jwt_secret_key: str = DEFAULT_JWT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    frontend_origin: AnyUrl = "http://localhost:3000"
    auth_cookie_secure: bool = False

    ai_rag_enabled: bool = False
    ai_agent_provider: Literal["openai", "gemini", "anthropic", "mock"] = "openai"
    ai_embedding_provider: Literal["openai", "mock"] = "openai"
    ai_agent_model: str = ""
    ai_embedding_model: str = ""
    ai_embedding_dimensions: int | None = None
    ai_request_timeout_seconds: int = 60
    ai_agent_max_iterations: int = 6
    ai_agent_max_tool_calls: int = 5
    rag_top_k: int = 5
    rag_prompt_version: str = "v1"

    mcp_server_enabled: bool = False
    mcp_allowed_tools: str = DEFAULT_MCP_ALLOWED_TOOLS
    mcp_request_timeout_seconds: int = 30

    openai_api_key: str = ""
    openai_base_url: str = ""
    gemini_api_key: str = ""
    gemini_base_url: str = ""
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    law_open_api_oc: str = ""

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE,),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("ai_embedding_dimensions", mode="before")
    @classmethod
    def parse_optional_embedding_dimensions(cls, value: object) -> object:
        # .env의 빈 값(AI_EMBEDDING_DIMENSIONS=)은 아직 미설정 상태로 취급합니다.
        if value == "":
            return None
        return value

    @property
    def mcp_allowed_tool_names(self) -> list[str]:
        # list 필드는 pydantic-settings가 JSON으로 해석하므로 원본 env 문자열을 직접 나눕니다.
        return [
            tool.strip()
            for tool in self.mcp_allowed_tools.split(",")
            if tool.strip()
        ]

    @model_validator(mode="after")
    def validate_ai_rag_settings(self) -> "Settings":
        errors: list[str] = []

        def add_error(message: str) -> None:
            if message not in errors:
                errors.append(message)

        def is_blank(value: str) -> bool:
            return value.strip() == ""

        positive_integer_fields = [
            ("AI_REQUEST_TIMEOUT_SECONDS", self.ai_request_timeout_seconds),
            ("AI_AGENT_MAX_ITERATIONS", self.ai_agent_max_iterations),
            ("AI_AGENT_MAX_TOOL_CALLS", self.ai_agent_max_tool_calls),
            ("RAG_TOP_K", self.rag_top_k),
            ("MCP_REQUEST_TIMEOUT_SECONDS", self.mcp_request_timeout_seconds),
        ]
        for name, value in positive_integer_fields:
            if value <= 0:
                add_error(f"{name} must be a positive integer")

        if self.mcp_server_enabled and not self.mcp_allowed_tool_names:
            add_error("MCP_ALLOWED_TOOLS is required when MCP_SERVER_ENABLED=true")

        # Provider key와 model은 RAG 기능을 명시적으로 켰을 때만 필수입니다.
        if self.ai_rag_enabled:
            if self.ai_agent_provider == "openai":
                if is_blank(self.openai_api_key):
                    add_error(
                        "OPENAI_API_KEY is required when AI_RAG_ENABLED=true "
                        "and AI_AGENT_PROVIDER=openai"
                    )
            elif self.ai_agent_provider == "gemini":
                if is_blank(self.gemini_api_key):
                    add_error(
                        "GEMINI_API_KEY is required when AI_RAG_ENABLED=true "
                        "and AI_AGENT_PROVIDER=gemini"
                    )
            elif self.ai_agent_provider == "anthropic":
                if is_blank(self.anthropic_api_key):
                    add_error(
                        "ANTHROPIC_API_KEY is required when AI_RAG_ENABLED=true "
                        "and AI_AGENT_PROVIDER=anthropic"
                    )

            if self.ai_agent_provider != "mock" and is_blank(self.ai_agent_model):
                add_error("AI_AGENT_MODEL is required when AI_RAG_ENABLED=true")

            if self.ai_embedding_provider == "openai":
                if is_blank(self.openai_api_key):
                    add_error(
                        "OPENAI_API_KEY is required when AI_RAG_ENABLED=true "
                        "and AI_EMBEDDING_PROVIDER=openai"
                    )
                if is_blank(self.ai_embedding_model):
                    add_error("AI_EMBEDDING_MODEL is required when AI_RAG_ENABLED=true")

            if (
                self.ai_embedding_dimensions is None
                or self.ai_embedding_dimensions <= 0
            ):
                add_error(
                    "AI_EMBEDDING_DIMENSIONS must be a positive integer "
                    "when AI_RAG_ENABLED=true"
                )

        if errors:
            raise ValueError("; ".join(errors))
        return self

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
