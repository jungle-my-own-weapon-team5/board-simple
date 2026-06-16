# MCP/Agent 설계

## 목적

이 문서는 법률정보 기반 분쟁 쟁점 정리·자료 검색·답변 초안 보조 시스템에서 MCP 서버와 AI Agent의 MVP 설계를 정의합니다.

핵심 방향:

- RAG 검색은 FastAPI service + pgvector로 명시적으로 구현합니다.
- MCP는 Agent가 사용할 수 있는 tool 경계를 표준화합니다.
- MVP는 멀티에이전트가 아니라 단일 Orchestrator Agent입니다.
- MCP tool은 Agent가 아닙니다. tool은 Orchestrator 또는 전문 Agent가 호출하는 제한된 service 경계입니다.
- Agent는 OpenAI API를 사용하되, Gemini/Claude로 확장 가능한 provider adapter 뒤에서 호출합니다.
- LangGraph는 MVP 필수 의존성으로 두지 않고, 명시적 bounded state machine으로 "LangGraph 또는 유사 구조" 요구를 충족합니다.
- 멀티에이전트 workflow는 MVP 안정화 이후 Supervisor Agent와 전문 Agent 구조로 확장합니다.

## 과제 요구사항 대응

| 과제 요구사항 | MVP 설계 |
| --- | --- |
| 상용 LLM 사용 | OpenAI API를 기본 generation provider로 사용 |
| RAG | pgvector 기반 내부 검색, citation 추적, `rag_runs`/`rag_retrievals` 저장 |
| MCP 서버 구현 | MVP에서는 FastAPI 내부 `POST /api/mcp` JSON-RPC endpoint 제공. 별도 local process는 후속 확장 |
| JSON-RPC request/response | `tools/list`, `tools/call` 형식의 JSON-RPC 계약 제공 |
| 실제 외부 서비스 연동 | `search_law_open_api` tool이 국가법령정보 Open API 호출 |
| API key/권한 전략 | `LAW_OPEN_API_OC`는 서버 환경변수에서만 읽고 로그/응답/DB에 저장하지 않음 |
| AI Agent | MVP는 단일 Orchestrator Agent. 후속 확장에서 Supervisor Agent와 전문 Agent로 분리 |
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
  contracts.py
  prompts.py
  citations.py
  supervisor.py
  agents/
    __init__.py
    issue_spotting.py
    retrieval.py
    legal_source.py
    drafting.py
    citation_verifier.py
    safety_review.py

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
| `agent/orchestrator.py` | MVP 단일 Orchestrator Agent 상태 흐름 실행 |
| `agent/state.py` | Agent state, step type, loop counter 정의 |
| `agent/contracts.py` | 후속 전문 Agent가 공유할 `AgentTask`, `AgentResult`, `AgentContext`, `AgentHandoff` 계약 |
| `agent/supervisor.py` | 후속 멀티에이전트 workflow의 전문 Agent 호출 순서, handoff, retry, 중단 조건 결정 |
| `agent/agents/*` | 후속 전문 Agent 구현 |
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
      "search_mode": "focused_answer",
      "top_k": 8,
      "score_threshold": null,
      "max_chunks_per_document": 5
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
search_mode: focused_answer | issue_spotting
top_k: int | null
score_threshold: float | null
max_chunks_per_document: int | null
filters: dict | null
```

출력:

```text
items: list[LegalSearchResult]
embedding_provider: str
embedding_model_name: str
```

이 tool은 직접 SQL 문자열을 받지 않습니다. repository/service 계층의 정해진 검색 함수만 호출합니다.

`focused_answer`는 답변 생성에 넣을 근거를 좁게 고르는 기본 모드이고, `issue_spotting`은 한 사건에서 여러 조문과 구성요건을 넓게 탐지하는 모드입니다. `issue_spotting`에서는 검색 누락을 줄이기 위해 `top_k` 기본값을 크게 두고, `max_chunks_per_document`는 호출자가 명시한 경우에만 적용합니다.

### `search_law_open_api`

국가법령정보 Open API 등 실제 외부 법률 API를 호출합니다.

입력:

```text
query: str
target: statute | case | interpretation | admin_appeal
limit: int
```

`target`은 내부 `document_type`과 같은 enum을 사용합니다. 국가법령정보 Open API의 실제 세부 구분값은 `legal_open_api` adapter 내부에서 매핑합니다.

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

MVP Agent는 하나의 `OrchestratorAgent`이며 다음 상태 흐름을 사용합니다.

```text
plan_issue_sources
  -> search_internal
  -> maybe_sync_official_sources
  -> search_internal_again
  -> decide
  -> draft
  -> verify
  -> persist
```

상태별 책임:

| State | 책임 |
| --- | --- |
| `plan_issue_sources` | 사용자 facts/question에서 후보 쟁점, 법률 영역, 후보 법령명, 내부 RAG query, 외부 공식 source query를 생성 |
| `search_internal` | `search_legal_documents`로 기존 공용 corpus와 사용자 범위 corpus를 먼저 검색 |
| `maybe_sync_official_sources` | 내부 근거가 부족할 때만 `search_law_open_api` 또는 ingestion sync service를 통해 공식 source metadata 확인과 제한된 on-demand sync 수행 |
| `search_internal_again` | 새 chunk embedding이 준비되었거나 기존 indexed 문서를 재사용할 수 있으면 내부 RAG를 재실행 |
| `decide` | 추가 검색이 필요한지, 근거 부족으로 응답해야 하는지, 초안을 작성할 수 있는지 판단 |
| `draft` | provider adapter를 통해 OpenAI generation 호출 |
| `verify` | `verify_citations`로 citation 검증 |
| `persist` | `rag_runs`, `rag_retrievals`, `agent_steps` 저장 |

MVP에서는 위 상태를 하나의 `OrchestratorAgent`가 수행합니다. 이 단계에서 MCP tool과 Agent를 혼동하지 않습니다. `search_legal_documents`, `search_law_open_api`, `verify_citations`는 Agent가 아니라 Orchestrator가 호출하는 tool입니다.

사용자 요청 기반 공식 corpus 보강 규칙:

- `plan_issue_sources`가 만든 후보 법령명과 외부 source query는 검색 계획이며, 그 자체를 citation으로 사용하지 않습니다.
- 공식 법령, 판례, 법령해석례, 행정심판례는 공용 corpus로 sync하고, 사용자 계약서/PDF/메모는 사용자 또는 tenant 범위 corpus로 유지합니다.
- on-demand sync는 요청당 후보 문서 수, tool 호출 수, provider timeout, API quota, rate limit을 적용합니다.
- `conflict_status=review_required`, `index_status=failed`, embedding 실패 문서는 evidence와 citation 후보에서 제외합니다.
- sync 또는 기존 indexed 문서 재사용 후에는 내부 RAG 검색을 다시 실행하고, 이 재검색 결과를 답변 근거로 사용합니다.

Agent는 다음 조건에서 중단합니다.

- `max_iterations` 초과
- `max_tool_calls` 초과
- tool timeout
- provider timeout 또는 provider error
- citation 검증 실패 후 복구 불가

중단 시에는 `rag_runs.status=failed` 또는 근거 부족 응답을 저장합니다.

## 멀티에이전트 확장 설계

단일 Orchestrator가 안정화된 뒤 다음 구조로 확장합니다.

```text
SupervisorAgent
  -> IssueSpottingAgent
  -> RetrievalAgent
  -> LegalSourceAgent
  -> DraftingAgent
  -> CitationVerifierAgent
  -> SafetyReviewAgent
```

Agent 역할:

| Agent | 책임 |
| --- | --- |
| `SupervisorAgent` | 전체 계획, Agent 호출 순서, handoff, retry, 중단 조건 결정 |
| `IssueSpottingAgent` | 사실관계에서 후보 쟁점, 법률 영역, 후보 법령명, 내부 RAG query, 외부 공식 source query, 누락 사실 추출 |
| `RetrievalAgent` | 내부 RAG 검색, `focused_answer`/`issue_spotting` 선택, 검색 결과 정리 |
| `LegalSourceAgent` | 국가법령정보 Open API 등 외부 공식 source 조회와 공용 corpus on-demand 보강 필요성 판단 및 결과 정리 |
| `DraftingAgent` | 검색된 evidence 기반 쟁점 정리 또는 답변 초안 작성 |
| `CitationVerifierAgent` | citation이 retrieved chunk 또는 외부 source metadata에 근거하는지 검증 |
| `SafetyReviewAgent` | 법률 자문 단정, 개인정보, secret, prompt injection 영향 검토 |

공통 계약:

```text
AgentTask
  task_type
  user_query
  facts
  evidence
  constraints

AgentResult
  status
  output
  citations
  confidence
  missing_facts
  requires_human_review

AgentContext
  run_id
  user_id
  prompt_version
  tool_budget
  evidence_set

AgentHandoff
  from_agent
  to_agent
  reason
  payload
```

멀티에이전트 규칙:

- `SupervisorAgent`만 다음 Agent 호출 순서를 결정합니다.
- 전문 Agent는 서로를 직접 호출하지 않습니다. 필요한 다음 작업은 `AgentHandoff`로 Supervisor에게 반환합니다.
- 전문 Agent는 provider SDK, database, filesystem을 직접 호출하지 않습니다.
- 내부 검색과 외부 source 조회는 기존 MCP tool 또는 service 경계를 사용합니다.
- citation 검증과 safety review는 최종 응답 전에 반드시 실행합니다.
- 각 Agent 실행과 handoff는 `agent_steps`에 audit metadata로 저장합니다. MVP 스키마에서는 기본 실행 metadata를 우선 저장하고, handoff reason/confidence/human review 같은 상세 필드는 후속 migration에서 확장할 수 있습니다.
- `max_iterations`, `max_tool_calls`, `max_agent_handoffs`, timeout으로 루프를 제한합니다.

LangGraph 도입 기준:

- 초기 멀티에이전트는 위 계약을 사용해 직접 구현한 `SupervisorAgent`로 시작할 수 있습니다.
- handoff, branching, retry, human-in-the-loop, 장기 실행 workflow가 복잡해지면 LangGraph로 이전합니다.
- LangGraph로 이전해도 MCP tool 계약, provider adapter 계약, RAG DB schema, citation 검증 정책은 유지합니다.
- LangGraph node는 전문 Agent 또는 검증 step을 감싸는 orchestration 계층이며, 법률 문서 모델이나 citation model의 소유자가 아닙니다.

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

- Supervisor Agent와 전문 Agent 기반 멀티에이전트 workflow 추가
- handoff, branching, retry, human-in-the-loop이 복잡해질 경우 LangGraph로 상태 흐름 이전
- 사용자 추가 질문과 human-in-the-loop
- progress streaming
- MCP tool별 권한 정책 세분화
- 법원, 공공데이터 등 source별 특화 adapter 추가
- 사용자 업로드 문서의 private corpus 분리
