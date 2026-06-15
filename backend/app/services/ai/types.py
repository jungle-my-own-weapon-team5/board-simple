# 이 파일은 OpenAI, Gemini, Claude, mock provider의 응답 차이를 backend 내부에서 숨기기 위한 공통 자료형

from dataclasses import dataclass, field


# request/result 객체를 중간에 실수로 바꾸지 않기 위함
@dataclass(frozen=True)
class AIUsage:
    """Provider별 token 사용량을 backend 공통 형식으로 표현합니다."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class AITextRequest:
    """텍스트 생성 provider에 전달할 표준 요청입니다."""

    prompt: str
    model: str
    timeout_seconds: int
    # 호출 목적, run id 같은 안전한 metadata만 담고 secret은 넣지 않습니다.
    metadata: dict[str, str] = field(default_factory=dict)
    temperature: float | None = None


@dataclass(frozen=True)
class AITextResult:
    """Provider별 생성 응답을 backend 공통 형식으로 정규화한 결과입니다."""

    text: str
    agent_provider: str
    agent_model_name: str
    finish_reason: str | None = None
    latency_ms: int | None = None
    usage: AIUsage | None = None
    raw_response_id: str | None = None


@dataclass(frozen=True)
class EmbeddingRequest:
    """Embedding provider에 전달할 표준 요청입니다."""

    texts: list[str]
    model: str
    dimensions: int
    timeout_seconds: int
    # Provider API key, Authorization header, 원본 사용자 개인정보는 넣지 않습니다.
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingResult:
    """Provider별 embedding 응답을 backend 공통 형식으로 정규화한 결과입니다."""

    embedding: list[float]
    embedding_provider: str
    embedding_model_name: str
    dimensions: int
    input_index: int