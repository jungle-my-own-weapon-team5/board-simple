# 이 파일은 OpenAI, mock, Gemini, Claude adapter가 반드시 구현해야 하는 메서드 계약
from abc import ABC, abstractmethod

from app.services.ai.types import (
    AITextRequest,
    AITextResult,
    EmbeddingRequest,
    EmbeddingResult,
)


class AIProvider(ABC):
    """모든 AI provider adapter가 따라야 하는 공통 인터페이스입니다."""

    provider_name: str

    @abstractmethod
    def generate_text(self, request: AITextRequest) -> AITextResult:
        """텍스트 생성 요청을 실행합니다."""
        pass

    @abstractmethod
    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        """여러 text를 embedding vector로 변환합니다."""
        pass