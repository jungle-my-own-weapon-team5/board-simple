# Provider Adapter 명세

## 목적

이 문서는 AI provider를 교체하거나 확장할 때 backend API와 RAG service가 흔들리지 않도록 공통 adapter 계약을 정의합니다.

MVP는 OpenAI API를 사용합니다. Gemini와 Claude는 같은 adapter 인터페이스를 구현하는 후속 provider로 추가합니다.

## 기본 원칙

- route handler는 provider SDK를 직접 호출하지 않습니다.
- RAG service는 `services/ai/client.py`만 호출합니다.
- provider별 SDK, 인증 방식, 오류 형식은 `services/ai/providers/*` 내부에 숨깁니다.
- provider 선택은 server-side 환경변수로만 결정합니다.
- 클라이언트 요청으로 provider를 선택하지 않습니다.
- API key는 환경변수에서만 읽고 로그, 응답, DB에 저장하지 않습니다.
- Agent가 tool 호출이 필요할 때도 provider SDK에 임의 tool 권한을 넘기지 않고, 서버 allowlist와 MCP tool registry를 통과시킵니다.

## Provider 설정값

| 설정값 | 표시명 | Generation | Embedding | MVP | 비고 |
| --- | --- | --- | --- | --- | --- |
| `openai` | OpenAI | yes | yes | yes | MVP 기본 provider |
| `gemini` | Google Gemini | yes | no | no | 후속 generation adapter |
| `anthropic` | Anthropic Claude | yes | conditional | no | 후속 generation adapter. embedding은 provider가 공식 지원하거나 호환 endpoint가 있을 때만 활성화 |
| `voyage` | Voyage AI | no | yes | no | Claude 생태계와 함께 고려 가능한 후속 embedding adapter |
| `mock` | Mock Provider | yes | yes | test | 테스트 전용 |

주의:

- `Claude`는 제품/모델 표시명이고, 환경변수 provider 값은 `anthropic`을 사용합니다.
- Gemini와 Claude는 우선 generation provider로만 취급합니다. embedding 기능이 없는 provider에서 `embed_texts`를 호출하면 `ProviderCapabilityError`를 반환합니다.
- embedding provider는 MVP에서 `openai`, 테스트에서 `mock`만 지원하는 것으로 시작하되, DB의 `embedding_profiles.provider`는 향후 `anthropic`, `voyage` 같은 provider를 schema 변경 없이 기록할 수 있게 문자열로 둡니다.

## 환경변수

```env
AI_RAG_ENABLED=false
AI_AGENT_PROVIDER=openai
AI_EMBEDDING_PROVIDER=openai
AI_AGENT_MODEL=
AI_EMBEDDING_MODEL=
AI_EMBEDDING_DIMENSIONS=
AI_REQUEST_TIMEOUT_SECONDS=60
AI_AGENT_MAX_ITERATIONS=6
AI_AGENT_MAX_TOOL_CALLS=5
RAG_TOP_K=5
RAG_PROMPT_VERSION=v1

MCP_SERVER_ENABLED=false
MCP_ALLOWED_TOOLS=search_legal_documents,search_law_open_api,verify_citations
MCP_REQUEST_TIMEOUT_SECONDS=30

OPENAI_API_KEY=
OPENAI_BASE_URL=

GEMINI_API_KEY=
GEMINI_BASE_URL=

ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=
```

검증 정책:

- `AI_RAG_ENABLED=false`이면 provider key와 model 설정이 비어 있어도 됩니다.
- `AI_RAG_ENABLED=true`이면 모든 환경에서 provider 설정을 검증합니다.
- `AI_RAG_ENABLED=true`이고 `AI_AGENT_PROVIDER=openai`이면 `OPENAI_API_KEY`와 `AI_AGENT_MODEL`이 필요합니다.
- `AI_RAG_ENABLED=true`이고 `AI_EMBEDDING_PROVIDER=openai`이면 `OPENAI_API_KEY`, `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_DIMENSIONS`가 필요합니다.
- `AI_EMBEDDING_DIMENSIONS`는 양의 정수여야 합니다.
- provider별 key 누락 오류는 key 값을 포함하지 않아야 합니다.
- `MCP_SERVER_ENABLED=true`이면 allowlist와 timeout 설정을 검증합니다.
- `AI_AGENT_MAX_ITERATIONS`와 `AI_AGENT_MAX_TOOL_CALLS`는 양의 정수여야 합니다.

## 패키지 구조

```text
backend/app/services/ai/
  __init__.py
  client.py
  errors.py
  types.py
  providers/
    __init__.py
    base.py
    openai.py
    gemini.py
    anthropic.py
    mock.py
```

MVP에서 실제로 필요한 파일:

```text
client.py
errors.py
types.py
providers/base.py
providers/openai.py
providers/mock.py
```

Gemini와 Anthropic adapter는 후속 단계에서 추가합니다.

## 공통 타입

### `AITextRequest`

```text
prompt: str
model: str
temperature: float | None
timeout_seconds: int
metadata: dict[str, str]
```

### `AITextResult`

```text
text: str
agent_provider: str
agent_model_name: str
finish_reason: str | None
latency_ms: int | None
usage: AIUsage | None
raw_response_id: str | None
```

### `EmbeddingRequest`

```text
texts: list[str]
model: str
dimensions: int
timeout_seconds: int
metadata: dict[str, str]
```

### `EmbeddingResult`

```text
embedding: list[float]
embedding_provider: str
embedding_model_name: str
dimensions: int
input_index: int
```

## Embedding profile 계약

Embedding service는 provider 응답을 저장하기 전에 `embedding_profiles`를 기준으로 검증합니다.

필수 검증:

- `embedding_profile.provider`와 실제 선택된 provider가 일치해야 합니다.
- `embedding_profile.model_name`과 요청 model이 일치해야 합니다.
- 각 embedding vector 길이는 `embedding_profile.dimensions`와 일치해야 합니다.
- 같은 검색 요청에서는 하나의 `embedding_profile_id`만 사용해야 합니다.
- 다른 provider/model/dimension profile의 vector를 한 ranking 안에서 직접 비교하지 않아야 합니다.

model deprecation 정책:

- 기존 profile은 삭제하지 않고 `deprecated` 또는 `retired` 상태로 표시합니다.
- 새 model 또는 새 dimension은 새 `embedding_profiles` row로 생성합니다.
- 기존 chunk는 새 profile로 재임베딩하고, retrieval은 명시적으로 선택된 active profile만 사용합니다.

### `AIUsage`

```text
input_tokens: int | None
output_tokens: int | None
total_tokens: int | None
```

## 공통 인터페이스

`providers/base.py`는 다음 interface를 제공합니다.

```text
generate_text(request: AITextRequest) -> AITextResult
embed_texts(request: EmbeddingRequest) -> list[EmbeddingResult]
```

provider가 특정 기능을 지원하지 않으면 명시적인 오류를 반환합니다.

Agent tool 호출은 이 provider adapter의 책임이 아닙니다. Provider adapter는 텍스트 생성과 embedding 호출만 담당하고, MCP tool 선택과 실행은 `docs/mcp-agent-design.md`의 Agent orchestration이 담당합니다.

예:

```text
AnthropicProvider.embed_texts(...) -> ProviderCapabilityError
GeminiProvider.embed_texts(...) -> ProviderCapabilityError
```

## Error Mapping

| 내부 오류 | HTTP status | 설명 |
| --- | --- | --- |
| `ProviderConfigError` | 500 | 서버 provider 설정 오류 |
| `ProviderAuthError` | 502 | provider 인증 실패 |
| `ProviderRateLimitError` | 429 | provider rate limit |
| `ProviderTimeoutError` | 503 | provider timeout |
| `ProviderUnavailableError` | 503 | provider 장애 또는 일시적 사용 불가 |
| `ProviderCapabilityError` | 400 또는 500 | 선택한 provider가 기능을 지원하지 않음 |
| `ProviderResponseError` | 502 | provider 응답 파싱 실패 |

원칙:

- provider 원본 오류 메시지를 그대로 사용자에게 반환하지 않습니다.
- secret, API key, request header는 로그에 남기지 않습니다.
- 내부 로그에는 provider, model, error code, latency만 남깁니다.

## Timeout과 Retry

MVP 기본값:

```text
AI_REQUEST_TIMEOUT_SECONDS=60
```

권장 정책:

- generation request: timeout 60초
- embedding request: timeout 60초
- provider 429/5xx는 짧은 exponential backoff를 고려
- 사용자가 같은 요청을 반복 제출하지 않도록 frontend pending 상태를 표시
- retry 후에도 실패하면 `rag_runs.status=failed`로 저장

## DB 저장

`rag_runs`에는 다음 provider metadata를 저장합니다.

```text
agent_provider           # generation run only; retrieval-only run may be null
agent_model_name         # generation run only; retrieval-only run may be null
embedding_provider
embedding_model_name
prompt_version
```

저장하지 않는 값:

```text
OPENAI_API_KEY
GEMINI_API_KEY
ANTHROPIC_API_KEY
Authorization header
raw JWT
auth cookie
```

## 테스트 전략

필수 테스트:

- provider selection test
- missing key validation test
- unsupported capability test
- provider timeout mapping test
- provider error mapping test
- mock provider generation test
- mock provider embedding dimension test

MVP 테스트는 실제 OpenAI API를 호출하지 않고 mock provider로 수행합니다.

