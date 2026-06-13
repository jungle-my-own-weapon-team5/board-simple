# MCP/Agent 설계

## 목적

이 문서는 법률정보 기반 분쟁 쟁점 정리·자료 검색·답변 초안 보조 시스템에서 MCP 서버와 AI Agent의 MVP 설계를 정의합니다.

핵심 방향:

- RAG 검색은 FastAPI service + pgvector로 명시적으로 구현합니다.
- MCP는 Agent가 사용할 수 있는 tool 경계를 표준화합니다.
- Agent는 OpenAI API를 사용하되, Gemini/Claude로 확장 가능한 provider adapter 뒤에서 호출합니다.
- LangGraph는 MVP 필수 의존성으로 두지 않고, 명시적 bounded state machine으로 "LangGraph 또는 유사 구조" 요구를 충족합니다.

## 과제 요구사항 대응

| 과제 요구사항 | MVP 설계 |
| --- | --- |
| 상용 LLM 사용 | OpenAI API를 기본 generation provider로 사용 |
| RAG | pgvector 기반 내부 검색, citation 추적, `rag_runs`/`rag_retrievals` 저장 |
| MCP 서버 구현 | FastAPI 내부 또는 별도 local process로 MCP JSON-RPC endpoint 제공 |
| JSON-RPC request/response | `tools/list`, `tools/call` 형식의 JSON-RPC 계약 제공 |
| 실제 외부 서비스 연동 | `search_law_open_api` tool이 국가법령정보 Open API 호출 |
| API key/권한 전략 | `LAW_OPEN_API_OC`는 서버 환경변수에서만 읽고 로그/응답/DB에 저장하지 않음 |
| AI Agent | bounded state machine으로 계획, tool 선택, 실행, 관찰, 초안 작성, 검증 수행 |
| function/tool calling | Agent가 MCP tool registry를 통해 allowlist된 tool만 호출 |
| state/memory | `rag_runs`, `rag_retrievals`, `agent_steps`에 실행 상태와 audit 저장 |
| 무한 루프 방지 | `max_iterations`, `max_tool_calls`, timeout, 실패 상태 저장 |

## 컴포넌트

권장 패키지 구조:

```text
backend/app/services/mcp/
  __init__.py
  server.py
  registry.py
  types.py
  errors.py
  tools/
    __init__.py
    legal_documents.py
    legal_open_api.py
    citations.py

backend/app/services/agent/
  __init__.py
  orchestrator.py
  state.py
  prompts.py
  citations.py

backend/app/repositories/
  agent_steps.py

backend/app/api/
  mcp.py
  ai.py
```

역할:

| 컴포넌트 | 책임 |
| --- | --- |
| `mcp/server.py` | JSON-RPC request parsing, response/error formatting |
| `mcp/registry.py` | tool allowlist, schema validation, dispatch |
| `mcp/tools/legal_documents.py` | 내부 RAG retrieval service 호출 |
| `mcp/tools/legal_open_api.py` | 외부 법률 API 호출과 응답 정규화 |
| `mcp/tools/citations.py` | citation이 retrieved chunk 또는 외부 source에 근거하는지 검증 |
| `agent/orchestrator.py` | Agent 상태 흐름 실행 |
| `agent/state.py` | Agent state, step type, loop counter 정의 |
| `repositories/agent_steps.py` | step audit 저장 |

## MCP JSON-RPC 계약

MVP에서 지원할 method:

- `tools/list`
- `tools/call`

`tools/list`는 allowlist된 tool만 반환합니다.

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "tools/list",
  "params": {}
}
```

`tools/call`은 tool 이름과 arguments를 받습니다.

```json
{
  "jsonrpc": "2.0",
  "id": "req-2",
  "method": "tools/call",
  "params": {
    "name": "search_legal_documents",
    "arguments": {
      "query": "임대차 보증금 반환",
      "top_k": 5
    }
  }
}
```

오류 응답:

```json
{
  "jsonrpc": "2.0",
  "id": "req-2",
  "error": {
    "code": -32602,
    "message": "Invalid tool arguments",
    "data": {
      "error_code": "mcp_invalid_arguments"
    }
  }
}
```

오류 메시지는 secret, Authorization header, raw JWT, 전체 provider request/response를 포함하지 않습니다.

## MCP Tool

### `search_legal_documents`

내부 pgvector retrieval service를 호출합니다.

입력:

```text
query: str
top_k: int
filters: dict | null
```

출력:

```text
items: list[LegalSearchResult]
embedding_provider: str
embedding_model_name: str
```

이 tool은 직접 SQL 문자열을 받지 않습니다. repository/service 계층의 정해진 검색 함수만 호출합니다.

### `search_law_open_api`

국가법령정보 Open API 등 실제 외부 법률 API를 호출합니다.

입력:

```text
query: str
target: law | prec | interpretation
limit: int
```

출력:

```text
items:
  external_id
  title
  source_url
  published_date
  summary
```

규칙:

- `LAW_OPEN_API_OC`는 환경변수에서만 읽습니다.
- API key는 request log, response, DB에 저장하지 않습니다.
- 외부 API timeout과 rate limit 오류를 정제된 오류로 변환합니다.
- 응답 XML/JSON parsing은 명시적으로 처리하고, 실패 시 tool error로 반환합니다.

### `verify_citations`

생성 초안의 citation이 실제 검색 결과에 근거하는지 검증합니다.

입력:

```text
run_id: int
citations: list[CitationCandidate]
```

출력:

```text
valid: list[Citation]
invalid: list[CitationValidationError]
```

규칙:

- 해당 run의 `rag_retrievals`에 없는 chunk ID는 invalid로 처리합니다.
- 외부 API source는 tool 결과 metadata에 포함된 `external_id` 또는 `source_url` 기준으로 검증합니다.
- 모델이 임의로 만든 판례, 조문, URL은 제거하거나 한계로 표시합니다.

## Agent State Machine

MVP Agent는 다음 상태 흐름을 사용합니다.

```text
plan
  -> call_tool
  -> observe
  -> decide
  -> draft
  -> verify
  -> persist
```

상태별 책임:

| State | 책임 |
| --- | --- |
| `plan` | 사용자 facts/question을 분석하고 필요한 tool 후보를 정함 |
| `call_tool` | MCP registry를 통해 allowlist된 tool 호출 |
| `observe` | tool 결과를 evidence로 정리 |
| `decide` | 추가 검색이 필요한지, 초안을 작성할 수 있는지 판단 |
| `draft` | provider adapter를 통해 OpenAI generation 호출 |
| `verify` | `verify_citations`로 citation 검증 |
| `persist` | `rag_runs`, `rag_retrievals`, `agent_steps` 저장 |

Agent는 다음 조건에서 중단합니다.

- `max_iterations` 초과
- `max_tool_calls` 초과
- tool timeout
- provider timeout 또는 provider error
- citation 검증 실패 후 복구 불가

중단 시에는 `rag_runs.status=failed` 또는 근거 부족 응답을 저장합니다.

## Function/Tool Calling 정책

MVP에서 모델에게 unrestricted tool 권한을 넘기지 않습니다.

허용 흐름:

```text
Agent orchestrator
  -> MCP tool registry
  -> allowlist/schema validation
  -> backend service or external API client
```

금지 흐름:

```text
LLM provider
  -> arbitrary filesystem/shell/database/API
```

OpenAI의 function calling 또는 tool calling 기능을 사용하더라도, 실제 실행은 서버의 MCP registry가 검증한 tool name과 arguments에 대해서만 수행합니다.

## 상태 저장

`rag_runs`:

- run type
- query/facts 저장 정책
- status
- provider/model metadata
- prompt version
- answer/disclaimer

`rag_retrievals`:

- chunk ID
- rank
- score
- retrieval type

`agent_steps`:

- step index
- step type
- tool name
- status
- redacted input/output metadata
- error code/message

저장하지 않는 값:

- API key
- Authorization header
- raw JWT
- auth cookie
- provider raw request/response 전문
- 외부 API key가 포함된 URL

## 권한과 보안

- MCP endpoint는 일반 사용자가 임의 tool을 호출하는 공개 API로 설계하지 않습니다.
- 사용자의 AI 요청은 backend API에서 인증과 rate limit을 통과한 뒤 Agent로 전달됩니다.
- Agent는 서버 설정의 allowlist만 사용합니다.
- ingestion, re-index, source sync는 admin role 도입 후 admin-only로 제한합니다.
- 외부 API 호출은 timeout, retry 제한, rate limit 처리를 둡니다.
- 모든 오류는 secret redaction 후 사용자에게 반환합니다.

## 테스트 기준

필수 테스트:

- `tools/list`가 allowlist된 tool만 반환
- unknown tool 호출 거부
- tool argument validation 실패 처리
- `search_legal_documents` mock retrieval 성공
- `search_law_open_api` mock HTTP 성공/실패/timeout 처리
- `verify_citations`가 존재하지 않는 chunk ID 거부
- Agent 정상 흐름에서 `agent_steps` 저장
- `max_tool_calls` 초과 시 중단
- provider 실패 시 안전한 오류 mapping
- secret 값이 로그, 응답, DB에 저장되지 않음

## 후속 확장

- LangGraph로 상태 흐름 이전
- 사용자 추가 질문과 human-in-the-loop
- progress streaming
- MCP tool별 권한 정책 세분화
- 판례/행정심판/공공데이터 API 추가
- 사용자 업로드 문서의 private corpus 분리
