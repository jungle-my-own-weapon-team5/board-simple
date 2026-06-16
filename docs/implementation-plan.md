# 구현계획

## 목표

현재 게시판 템플릿을 유지하면서 FastAPI + pgvector 기반 명시적 RAG 구조와 MCP/Agent 기능을 단계적으로 추가합니다.

MVP의 AI agent/generation provider와 embedding provider는 OpenAI API를 사용합니다. MCP 서버는 실제 외부 법률 API tool을 포함하고, MVP Agent는 단일 `OrchestratorAgent`로 bounded reasoning loop/state machine을 통해 action 제안, 검증, tool 호출을 조율합니다. Gemini와 Claude는 같은 provider adapter 인터페이스로 후속 확장합니다.

## 전제

- 기존 게시판 API와 테스트를 깨지 않습니다.
- RAG 구현은 route handler가 아니라 service/repository/model/schema 계층에 추가합니다.
- secret 값은 `.env`에만 두고 출력하거나 commit하지 않습니다.
- `.env.example`에는 secret placeholder만 둡니다.
- Docker Compose에서 AI provider 변수를 backend container로 전달하는 작업은 AI 구현 단계에 포함합니다.
- backend 로컬 개발은 Python 3.12 가상환경과 `python -m pip install -r backend/requirements-dev.txt` 기준으로 의존성을 설치합니다.
- 로컬 개발 DB는 PostgreSQL 17 + pgvector 설치본을 기본으로 사용하고, 전체 Docker 실행은 별도 검증 경로로 유지합니다.
- MCP와 Agent는 과제 요구사항 충족을 위해 MVP 범위에 포함합니다.

## 단계별 계획

## 0단계: 문서와 설정 정리

상태: 이번 작업 범위

작업:

- `.env.example`에 AI provider와 RAG 설정 변수 추가
- `docs/architecture.md`에 OpenAI MVP와 provider adapter 전략 반영
- `docs/api-spec.md`에 AI provider 규칙 반영
- `docs/requirements.md`에 provider adapter 요구사항 추가
- `docs/db-design.md` 작성
- `docs/implementation-plan.md` 작성
- `docs/provider-adapter-spec.md` 작성
- `docs/security-privacy.md` 작성
- `docs/rag-pipeline.md` 작성
- `docs/evaluation-plan.md` 작성
- `docs/mcp-agent-design.md` 작성

검증:

- 문서가 UTF-8 without BOM인지 확인
- CRLF 줄바꿈 확인
- 한글 표시 확인
- secret 값이 포함되지 않았는지 확인

## 1단계: 설정 모델 확장

목표:

- backend 설정에서 AI/RAG 환경변수를 읽을 수 있게 합니다.

예상 수정 파일:

```text
backend/app/core/config.py
docker-compose.yml
backend/tests/test_config.py
```

추가 설정 후보:

```text
AI_RAG_ENABLED
AI_AGENT_PROVIDER
AI_EMBEDDING_PROVIDER
AI_AGENT_MODEL
AI_EMBEDDING_MODEL
AI_EMBEDDING_DIMENSIONS
AI_REQUEST_TIMEOUT_SECONDS
AI_AGENT_MAX_HANDOFFS
AI_RATE_LIMIT_PER_MINUTE
RAG_TOP_K
RAG_PROMPT_VERSION
API_REQUEST_BODY_MAX_BYTES
OPENAI_API_KEY
OPENAI_BASE_URL
GEMINI_API_KEY
GEMINI_BASE_URL
ANTHROPIC_API_KEY
ANTHROPIC_BASE_URL
LAW_OPEN_API_OC
LAW_OPEN_API_BASE_URL
LAW_OPEN_API_SERVICE_URL
```

구현 기준:

- `AI_RAG_ENABLED=false`인 동안에는 OpenAI key와 model 설정이 비어 있어도 됩니다.
- `AI_RAG_ENABLED=true`에서는 모든 환경에서 OpenAI MVP 사용 시 `OPENAI_API_KEY`, `AI_AGENT_MODEL`, `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_DIMENSIONS` 존재를 검증하고, 실패하면 애플리케이션 시작을 중단합니다.
- `APP_ENV=production`에서는 위 검증에 더해 운영용 JWT, HTTPS origin, secure cookie 같은 기존 운영 안전 설정도 함께 강제합니다.
- key 값은 validation 오류 메시지나 로그에 출력하지 않습니다.
- `AI_AGENT_PROVIDER` 허용값은 최소 `openai`, `gemini`, `anthropic`, `mock`으로 제한합니다.
- `AI_EMBEDDING_PROVIDER` 허용값은 최소 `openai`, `mock`으로 시작합니다.
- `AI_EMBEDDING_DIMENSIONS`는 양의 정수로 검증합니다.

검증:

- 설정 unit test 추가
- production에서 필수 key 누락 시 실패 확인
- secret 값이 출력되지 않는지 확인

## 2단계: AI provider adapter 골격

목표:

- route와 RAG service가 provider SDK에 직접 의존하지 않게 합니다.

예상 추가 파일:

```text
backend/app/services/ai/__init__.py
backend/app/services/ai/client.py
backend/app/services/ai/providers/__init__.py
backend/app/services/ai/providers/base.py
backend/app/services/ai/providers/openai.py
backend/app/services/ai/providers/mock.py
backend/tests/test_ai_providers.py
```

권장 인터페이스:

```text
generate(prompt, *, model, timeout) -> AITextResult
embed(texts, *, model, dimensions, timeout) -> list[EmbeddingResult]
```

구현 기준:

- MVP는 OpenAI adapter를 구현합니다.
- 테스트는 mock provider로 실행합니다.
- provider error는 내부 error type으로 변환합니다.
- provider 응답에는 provider/model metadata와 latency metadata를 포함합니다.
- 세부 계약은 `docs/provider-adapter-spec.md`를 따릅니다.

검증:

- mock provider unit test
- OpenAI key가 없을 때 OpenAI adapter 생성이 안전하게 실패하는지 확인
- provider error mapping test

## 3단계: RAG DB schema 추가

목표:

- 법률 source, document, chunk, AI run, retrieval audit를 저장할 수 있게 합니다.

예상 수정/추가 파일:

```text
backend/app/models/legal_source.py
backend/app/models/legal_document.py
backend/app/models/document_chunk.py
backend/app/models/embedding.py
backend/app/models/rag_run.py
backend/app/models/__init__.py
backend/alembic/versions/0003_rag_schema.py
backend/app/repositories/legal_documents.py
backend/app/repositories/document_chunks.py
backend/app/repositories/embeddings.py
backend/app/repositories/rag_runs.py
backend/tests/test_rag_repositories.py
```

구현 기준:

- `docs/db-design.md`의 schema를 기준으로 합니다.
- `legal_document_chunks`에는 embedding vector와 embedding 상태를 두지 않습니다.
- `embedding_profiles`와 `legal_document_chunk_embeddings`로 provider/model/dimension별 vector를 분리합니다.
- 초기에는 vector index를 생성하지 않아도 됩니다.
- generation run에는 `rag_runs.agent_provider`, `rag_runs.agent_model_name`을 저장합니다.
- 모든 RAG run에는 `rag_runs.embedding_profile_id`, `rag_runs.embedding_provider`, `rag_runs.embedding_model_name`, `rag_runs.embedding_dimensions`, `rag_runs.prompt_version`을 저장합니다.
- `legal_documents`에는 indexing 상태 필드를, `legal_document_chunk_embeddings`에는 embedding 상태 필드를 추가합니다.
- `legal_documents`에 `raw_checksum`, `normalized_checksum`, `dedup_status`, `conflict_status`, `duplicate_of_document_id`를 추가합니다.
- `source_type`과 `document_type`의 허용값은 `statute`, `case`, `interpretation`, `admin_appeal`, `user_file`, `memo`로 맞춥니다.
- `legal_documents.normalized_text`는 생성 직후 또는 indexing 전에는 null을 허용합니다.
- checksum 단독 unique constraint는 만들지 않습니다.
- 중복 판단은 `document_type`, `canonical_id`, `version_label` 또는 `effective_date`, `normalized_checksum` 조합을 기준으로 합니다.
- 같은 canonical/version인데 `normalized_checksum`이 다르면 자동 삭제하지 않고 `conflict_status=review_required`로 저장할 수 있게 합니다.
- `run_type=search`는 generation을 수행하지 않으므로 `agent_provider`, `agent_model_name`은 null을 허용합니다.

검증:

- Alembic upgrade 테스트
- repository create/read 테스트
- 하나의 chunk에 여러 embedding profile row를 저장할 수 있는지 테스트
- 서로 다른 dimension profile을 하드코딩 없이 저장할 수 있는지 테스트
- normalized checksum 기반 중복 후보 저장 테스트
- 같은 canonical/version의 checksum 충돌 상태 테스트
- 다른 `effective_date` 또는 `version_label`은 별도 version으로 보존되는지 테스트

## 4단계: Fixture ingestion과 chunking

목표:

- 외부 API 없이도 반복 가능한 RAG 테스트 데이터를 만들 수 있게 합니다.

예상 추가 파일:

```text
backend/app/services/rag/ingestion.py
backend/app/services/rag/chunking.py
backend/tests/fixtures/legal_documents/
backend/tests/test_rag_chunking.py
backend/tests/test_rag_ingestion.py
```

구현 기준:

- raw text와 normalized text를 모두 저장합니다.
- chunk는 `document_id`, `chunk_index`, `heading`, `content`, `metadata_json`을 가집니다.
- 법령/판례 fixture를 최소 1개씩 둡니다.
- 세부 파이프라인은 `docs/rag-pipeline.md`를 따릅니다.

검증:

- 같은 fixture를 여러 번 ingest해도 `normalized_checksum`과 canonical/version metadata로 중복을 감지합니다.
- 같은 canonical/version인데 정규화 본문이 달라지면 conflict review 상태를 기록합니다.
- 같은 canonical document라도 `effective_date` 또는 `version_label`이 다르면 별도 version으로 보존합니다.
- chunk 순서가 안정적인지 확인합니다.
- 한글 text가 깨지지 않는지 확인합니다.

## 5단계: Embedding과 vector retrieval

목표:

- chunk embedding을 저장하고 pgvector similarity search로 검색합니다.

예상 추가 파일:

```text
backend/app/services/rag/embeddings.py
backend/app/services/rag/retrieval.py
backend/app/repositories/embeddings.py
backend/app/schemas/ai.py
backend/app/api/rag.py
backend/tests/test_rag_retrieval.py
```

구현 기준:

- 테스트에서는 mock embedding을 사용합니다.
- MVP 실제 실행은 OpenAI embedding provider를 사용합니다.
- embedding service는 선택된 `embedding_profile_id`의 provider/model/dimension을 기준으로 provider 응답을 검증합니다.
- 같은 chunk는 여러 profile로 임베딩될 수 있지만, retrieval은 하나의 profile만 선택해 수행합니다.
- `/api/rag/search`는 답변 생성 없이 검색 결과만 반환합니다.
- `/api/rag/search`는 `search_mode`, `top_k`, `score_threshold`, `max_chunks_per_document`, metadata filter를 지원합니다.
- `search_mode=focused_answer`는 답변 생성용 근거를 좁게 선택하고, `search_mode=issue_spotting`은 다수 쟁점 탐지를 위해 쟁점별 검색 예산을 넓게 둡니다.
- 내부 RAG 검색 전 issue/source planning을 먼저 수행하고, `top_k`는 전체 입력이 아니라 계획된 각 쟁점별 query에 적용합니다.
- 같은 chunk가 여러 쟁점에서 검색되면 중복을 병합하고 `planned_issue_key`, `planned_issue_title`, `planned_issue_query`, `planned_issue_queries` metadata를 보존합니다.
- 검색 결과에는 `run_id`, `embedding_profile_id`, `embedding_provider`, `embedding_model_name`, `embedding_dimensions`, `chunk_embedding_id`, `chunk_id`, `document_id`, `rank`, `score`, `title`, `source_url`, `heading`, `content`를 포함합니다.
- 검색 요청도 `rag_runs.run_type=search`와 `rag_retrievals`에 저장합니다.

검증:

- fixture dataset으로 검색 결과 순위 테스트
- 인증 필요 여부 테스트
- `top_k` validation 테스트
- `score_threshold` validation과 filtering 테스트
- `max_chunks_per_document` 적용 테스트
- `focused_answer`와 `issue_spotting` 기본값 테스트

## 6단계: MCP 서버와 tool registry

목표:

- Agent가 사용할 수 있는 tool 경계를 MCP JSON-RPC 형식으로 제공합니다.

예상 추가 파일:

```text
backend/app/services/mcp/server.py
backend/app/services/mcp/registry.py
backend/app/services/mcp/types.py
backend/app/services/mcp/errors.py
backend/app/api/mcp.py
backend/tests/test_mcp_server.py
```

구현 기준:

- JSON-RPC request/response 구조를 검증합니다.
- `tools/list`는 allowlist된 tool만 반환합니다.
- `tools/call`은 allowlist에 없는 tool을 거부합니다.
- MCP 서버는 MVP에서 FastAPI 내부 `POST /api/mcp`로 제공하고, 인증된 backend/Agent 경로에서만 호출되도록 합니다.
- tool input/output은 secret을 제거한 metadata만 audit에 남깁니다.

검증:

- JSON-RPC schema validation 테스트
- unknown tool 거부 테스트
- tool timeout/error mapping 테스트
- secret redaction 테스트

## 7단계: MCP 법률 tool 구현

목표:

- 내부 RAG 검색과 실제 외부 법률 API 조회를 Agent가 동일한 tool 경계로 사용할 수 있게 합니다.

예상 추가 파일:

```text
backend/app/services/mcp/tools/legal_documents.py
backend/app/services/mcp/tools/legal_open_api.py
backend/app/services/mcp/tools/citations.py
backend/app/services/rag/legal_open_api.py
backend/tests/test_mcp_legal_tools.py
```

구현 기준:

- `search_legal_documents`는 5단계 retrieval service를 호출합니다.
- `search_legal_documents`는 단일 query retrieval primitive로 유지하고, API/Agent 상위 흐름은 issue/source planning 결과를 바탕으로 쟁점별 query를 여러 번 실행한 뒤 결과를 병합합니다.
- `search_law_open_api`는 국가법령정보 Open API 등 실제 외부 서비스를 호출합니다.
- `search_law_open_api.target`은 내부 문서 유형인 `statute`, `case`, `interpretation`, `admin_appeal`을 사용하고, 외부 API별 parameter는 adapter 내부에서 매핑합니다.
- `verify_citations`는 초안 citation이 해당 run의 retrieved chunk 또는 외부 source metadata에 근거하는지 확인합니다.
- `LAW_OPEN_API_OC`는 secret으로 취급합니다.
- `LAW_OPEN_API_BASE_URL`, `LAW_OPEN_API_SERVICE_URL`은 비밀값이 아닌 endpoint 설정이며, 운영 프록시나 테스트 서버가 필요할 때 환경별로 바꿀 수 있게 합니다.
- 외부 API 응답 XML/JSON parsing을 명시적으로 처리합니다.
- 외부 API 실패와 rate limit을 안전하게 처리합니다.

검증:

- tool별 request/response schema 테스트
- API client는 mock HTTP response로 테스트합니다.
- 실제 key 없이 테스트가 통과해야 합니다.
- key 값은 로그에 출력하지 않습니다.

## 8단계: Bounded AI Agent orchestration

목표:

- 쟁점/source 계획, action 제안, action 검증, MCP tool 호출, 관찰, 초안 작성, citation 검증을 하나의 제한된 단일 Orchestrator Agent reasoning loop로 묶습니다.
- MVP에서는 멀티에이전트가 아니라 단일 Orchestrator Agent를 구현합니다.

예상 추가 파일:

```text
backend/app/services/agent/orchestrator.py
backend/app/services/agent/state.py
backend/app/services/agent/prompts.py
backend/app/services/agent/citations.py
backend/app/repositories/agent_steps.py
backend/tests/test_agent_orchestrator.py
```

구현 기준:

- 상태 흐름은 `initialize_run -> plan_issue_sources -> reasoning_loop -> draft -> verify -> optional_repair_once -> persist`를 따릅니다.
- `reasoning_loop`는 `propose_action -> validate_action -> execute_tool_or_model_step -> observe -> decide_continue_or_stop` 반복으로 구성합니다.
- `plan_issue_sources`는 후보 쟁점, 법률 영역, 후보 법령명, 쟁점별 내부 RAG query, 외부 공식 source query를 생성합니다.
- 후보 법령명과 외부 source query는 검색 계획일 뿐이며, citation 가능한 근거는 retrieved chunk 또는 검증된 공식 source metadata로 제한합니다.
- LLM은 `AgentAction`을 제안하고, Orchestrator는 action type, tool name, arguments, 권한, 반복 여부를 검증한 뒤 실행합니다.
- 허용 action type은 `search_internal`, `search_external_source`, `sync_official_source`, `draft_answer`, `verify_citations`, `respond_insufficient_evidence`, `stop`입니다.
- `search_internal`은 기존 내부 RAG를 먼저 호출합니다.
- `search_external_source`와 `sync_official_source`는 내부 근거가 부족할 때만 공용 공식 corpus on-demand 보강을 시도합니다.
- on-demand 보강으로 새 embedding이 준비되거나 기존 indexed 문서를 재사용할 수 있으면 내부 RAG를 다시 호출합니다.
- `max_iterations`, `max_tool_calls`, `max_repeated_actions`, `max_external_sync_candidates`, timeout을 설정으로 제한합니다.
- 같은 action type과 arguments 조합이 반복되면 loop를 중단합니다.
- citation repair는 최대 1회만 허용합니다.
- 각 step은 `agent_steps`에 action type, tool name, redacted arguments summary, observation summary, decision reason, error metadata를 저장합니다.
- Agent는 allowlist된 MCP tool만 호출합니다.
- MCP tool은 Agent가 아니라 Orchestrator가 호출하는 제한된 service 경계입니다.
- OpenAI function/tool calling을 사용하더라도 모델 출력은 action 제안으로만 취급하고, 실제 실행은 서버 검증 뒤 수행합니다.
- 모델 응답은 provider adapter를 통해 OpenAI API로 생성합니다.
- 검색된 문서와 외부 API 결과는 prompt instruction이 아니라 evidence data로 취급합니다.

검증:

- LLM이 `search_internal` action을 선택하면 `search_legal_documents`가 실행되는지 테스트
- 허용되지 않은 action 또는 tool name은 실행하지 않고 실패 처리하는지 테스트
- 같은 action+arguments 반복 시 loop guard가 중단하는지 테스트
- `max_iterations`, `max_tool_calls`, `max_repeated_actions` 초과 중단 테스트
- 정상 action, observation, decision reason이 `agent_steps`에 저장되는지 테스트
- `max_tool_calls` 초과 중단 테스트
- tool 실패 시 안전 응답 테스트
- provider 실패 시 `502` 또는 `503` mapping 테스트

초기 evidence 부족 판단 기준:

- 내부 RAG 검색 결과 chunk가 0개이면 부족으로 판단합니다.
- citation 후보가 0개이면 부족으로 판단합니다.
- 위 조건에서만 `search_external_source` 또는 `sync_official_source` action을 허용합니다.

향후 evidence 평가 개선 기준:

- 쟁점별 coverage 계산
- 쟁점별 top-k 결과가 충분히 확보되었는지 확인
- 법령, 판례, 법령해석례, 행정심판례 등 source type 다양성 확인
- 최신 법령 여부 확인
- 공식 source 여부 확인
- top-k 결과가 하나의 문서 또는 하나의 조문에 과도하게 몰리는지 확인

권장 커밋 단위:

1. `feat(backend): Agent reasoning loop 계약 추가`
2. `feat(backend): Agent action 검증 및 loop guard 구현`
3. `feat(backend): Agent 공식 법령 source 보강 action 추가`
4. `feat(backend): Agent citation repair 흐름 추가`

## 9단계: 답변 초안 생성 API

목표:

- Agent orchestration 결과를 기반으로 쟁점 정리와 답변 초안을 반환합니다.

예상 추가 파일:

```text
backend/app/api/ai.py
backend/tests/test_ai_answer_drafts.py
```

구현 기준:

- `/api/ai/dispute-issues` 추가
- `/api/ai/answer-drafts` 추가
- 필요하면 `/api/ai/agent-runs`를 내부 공통 실행 endpoint로 둡니다.
- 응답에는 citation, disclaimer, `agent_provider`, `agent_model_name`을 포함합니다.
- `rag_runs`, `rag_retrievals`, `agent_steps`에 실행 결과를 저장합니다.

검증:

- citation 없는 법률 주장 방지 테스트
- disclaimer 포함 테스트
- provider/model 저장 테스트
- Agent step 저장 테스트

## 10단계: 프론트엔드 AI UI

목표:

- 사용자가 분쟁 사실관계를 입력하고 자료 검색/초안 생성을 실행할 수 있게 합니다.

예상 추가 파일:

```text
frontend/src/api/ai.ts
frontend/src/api/rag.ts
frontend/src/screens/DisputeAssistantPage.tsx
frontend/src/app/ai/page.tsx
frontend/src/types.ts
```

구현 기준:

- 검색 결과와 답변 초안을 분리해 보여줍니다.
- citation source를 사용자가 확인할 수 있게 합니다.
- pending/error 상태를 명확히 표시합니다.
- provider API key나 내부 prompt는 frontend에 노출하지 않습니다.

검증:

- frontend build
- 주요 화면 수동 확인
- 긴 답변과 citation 목록의 layout 확인

## 11단계: 외부 법률 API ingestion과 운영 정책

목표:

- 국가법령정보 Open API 등 허용된 법률 source를 ingestion하거나 MCP tool로 실시간 조회할 수 있게 합니다.
- 사용자 스토리 입력 후 내부 RAG 근거가 부족할 때, Orchestrator의 issue/source planning 결과를 바탕으로 공용 공식 corpus를 제한적으로 자동 보강할 수 있게 합니다.

예상 추가 파일:

```text
backend/app/services/legal_sources.py
backend/app/services/rag/legal_open_api.py
backend/app/services/rag/legal_open_api_sync.py
backend/tests/test_legal_sources.py
backend/tests/test_legal_open_api_sync.py
```

구현 기준:

- `LAW_OPEN_API_OC`는 secret으로 취급합니다.
- `LAW_OPEN_API_BASE_URL`, `LAW_OPEN_API_SERVICE_URL`은 비밀값이 아닌 endpoint 설정이며, ingestion client와 MCP tool이 같은 값을 사용합니다.
- MCP `search_law_open_api`와 ingestion client가 같은 parsing/error 정책을 공유합니다.
- 사용자 요청 기반 on-demand sync는 Agent reasoning loop의 `sync_official_source` action으로 실행하며, 내부 RAG 검색 후 근거 부족이 확인된 경우에만 허용합니다.
- on-demand sync 입력은 Orchestrator가 만든 후보 법령명, 외부 source query, target, search reason으로 구성합니다.
- on-demand sync는 요청당 후보 문서 수, API 호출 수, provider timeout, rate limit, quota를 제한합니다.
- 공식 법령, 판례, 법령해석례, 행정심판례는 사용자별 사본이 아니라 공용 `legal_sources`, `legal_documents`, `legal_document_chunks`, `legal_document_chunk_embeddings`로 저장합니다.
- 사용자 계약서, PDF, 메모는 사용자 또는 tenant 범위 corpus로 유지하며 공용 공식 corpus와 섞어 dedup하지 않습니다.
- source URL, external ID, fetched_at을 저장합니다.
- 전문 API를 호출하기 전에 metadata preflight를 수행합니다.
- preflight 응답에서 `provider`, `external_id`, `canonical_id`, `version_label`, `effective_date`, `published_date`를 추출해 기존 DB 문서와 비교합니다.
- 같은 canonical/version 문서가 이미 `index_status=indexed`이고 선택 embedding profile의 chunk embedding이 최신이면 전문 API, chunking, embedding API 호출을 생략하고 기존 DB 데이터를 사용합니다.
- 새 시행일 또는 새 version은 기존 문서를 덮어쓰지 않고 새 `legal_documents` row로 저장합니다.
- 같은 canonical/version인데 전문 재조회 후 `normalized_checksum`이 달라지면 `conflict_status=review_required`로 저장합니다.
- `conflict_status=review_required`, `index_status=failed`, embedding 실패 문서는 on-demand 응답의 citation 후보에서 제외합니다.
- sync와 embedding이 성공하거나 기존 indexed 문서를 재사용할 수 있으면 같은 요청에서 내부 RAG 검색을 다시 수행합니다.
- API timeout, rate limit, parsing failure는 안전한 내부 error로 변환하고 secret을 로그에 남기지 않습니다.

검증:

- API client는 mock HTTP response로 테스트합니다.
- 실제 key 없이 테스트가 통과해야 합니다.
- key 값은 로그에 출력하지 않습니다.
- preflight metadata만으로 기존 indexed 문서를 재사용하는 테스트를 추가합니다.
- 새 version metadata가 들어오면 전문 조회와 ingestion이 실행되는지 테스트합니다.
- 같은 canonical/version의 checksum 충돌이 conflict review로 저장되는지 테스트합니다.
- 기존 chunk와 embedding checksum이 최신이면 embedding provider가 호출되지 않는지 테스트합니다.
- 내부 RAG 근거 부족 시 on-demand sync가 호출되고, sync 후 retrieval이 재실행되는지 테스트합니다.
- 요청당 후보 문서 수와 tool 호출 수 제한을 초과하면 안전하게 중단되는지 테스트합니다.

## 12단계: Gemini/Claude provider 확장

목표:

- OpenAI MVP 이후 generation provider를 Gemini와 Claude로 확장할 수 있게 합니다.

예상 추가 파일:

```text
backend/app/services/ai/providers/gemini.py
backend/app/services/ai/providers/anthropic.py
backend/tests/test_ai_provider_selection.py
```

구현 기준:

- provider별 SDK 차이는 adapter 내부에 숨깁니다.
- `AI_AGENT_PROVIDER=gemini` 또는 `anthropic`으로 전환할 수 있게 합니다.
- request/response API shape는 유지합니다.
- provider별 timeout, retry, error mapping을 정리합니다.
- embedding provider는 별도로 유지합니다.

검증:

- provider selection unit test
- provider별 missing key validation test
- mock adapter로 API response shape 유지 확인

## 13단계: 멀티에이전트 workflow 확장

목표:

- 단일 Orchestrator가 안정적으로 동작한 뒤 Supervisor Agent와 전문 Agent 구조로 확장합니다.
- Agent 간 작업 순서, handoff, retry, 중단 조건을 명시적으로 관리합니다.

예상 추가 파일:

```text
backend/app/services/agent/contracts.py
backend/app/services/agent/supervisor.py
backend/app/services/agent/agents/__init__.py
backend/app/services/agent/agents/issue_spotting.py
backend/app/services/agent/agents/retrieval.py
backend/app/services/agent/agents/legal_source.py
backend/app/services/agent/agents/drafting.py
backend/app/services/agent/agents/citation_verifier.py
backend/app/services/agent/agents/safety_review.py
backend/tests/test_multi_agent_supervisor.py
```

구현 기준:

- `SupervisorAgent`가 전문 Agent 호출 순서, handoff, retry, 중단 조건을 결정합니다.
- 공통 계약은 `AgentTask`, `AgentResult`, `AgentContext`, `AgentHandoff`로 시작합니다.
- 전문 Agent는 서로를 직접 호출하지 않고 handoff 요청을 Supervisor에게 반환합니다.
- 전문 Agent는 provider SDK, DB, filesystem을 직접 호출하지 않고 service, MCP tool, provider adapter 경계를 사용합니다.
- `IssueSpottingAgent`는 후보 쟁점, 법률 영역, 후보 법령명, 내부 RAG query, 외부 공식 source query를 생성합니다.
- `RetrievalAgent`는 내부 RAG 검색과 재검색 전략을 선택합니다.
- `LegalSourceAgent`는 공용 공식 corpus의 on-demand 보강 필요성과 범위를 판단합니다.
- `DraftingAgent`, `CitationVerifierAgent`, `SafetyReviewAgent`를 단계적으로 추가합니다.
- citation 검증과 safety review는 최종 응답 전에 반드시 실행합니다.
- `max_agent_handoffs`, `max_iterations`, `max_tool_calls`, timeout으로 루프를 제한합니다.
- 각 Agent 실행과 handoff는 `agent_steps`에 저장합니다. 필요한 경우 후속 migration으로 `agent_name`, `parent_step_id`, `handoff_from_step_id`, `handoff_reason`, `confidence`, `requires_human_review`를 추가합니다.

LangGraph 도입 기준:

- 초기 멀티에이전트는 직접 구현한 `SupervisorAgent`로 시작합니다.
- handoff, branching, retry, human-in-the-loop, 장기 실행 workflow가 복잡해지면 LangGraph로 이전합니다.
- LangGraph를 도입해도 MCP tool 계약, provider adapter 계약, RAG DB schema, citation 검증 정책은 유지합니다.

검증:

- Supervisor가 올바른 전문 Agent 순서를 선택하는지 테스트
- Agent handoff metadata 저장 테스트
- `max_agent_handoffs` 초과 중단 테스트
- citation verifier와 safety review가 누락되지 않는지 테스트
- 잘못된 Agent 직접 호출 또는 tool 우회 방지 테스트

## 14단계: 품질과 보안 강화

목표:

- 법률/AI 기능을 외부 사용자에게 노출하기 전 안전장치를 강화합니다.

작업:

- AI endpoint rate limiting
- request body size limit
- PII redaction 또는 최소 저장 정책
- prompt injection test case
- retrieval evaluation fixture
- MCP allowlist와 JSON-RPC validation
- Agent loop guard와 tool failure handling
- admin role과 admin-only ingestion
- structured audit logging
- 세부 보안 기준은 `docs/security-privacy.md`를 따릅니다.
- 평가 기준은 `docs/evaluation-plan.md`를 따릅니다.

검증:

- 보안 회귀 테스트
- prompt injection fixture 테스트
- AI run audit record 확인
- MCP tool call audit record 확인
- Agent step audit record 확인

## 작업 순서 요약

```text
0. 문서와 .env.example 정리
1. 설정 모델 확장
2. AI provider adapter 골격
3. RAG DB schema 추가
4. fixture ingestion과 chunking
5. embedding과 vector retrieval
6. MCP 서버와 tool registry
7. MCP 법률 tool 구현
8. Bounded AI Agent orchestration
9. 답변 초안 생성 API
10. frontend AI UI
11. 외부 법률 API ingestion과 운영 정책
12. Gemini/Claude provider 확장
13. 멀티에이전트 workflow 확장
14. 품질과 보안 강화
```

## 완료 기준

MVP 완료 기준:

- OpenAI API 기반 provider adapter가 동작합니다.
- fixture 문서가 DB에 저장되고 chunk로 분리됩니다.
- chunk embedding이 `embedding_profiles`별로 pgvector에 저장됩니다.
- `/api/rag/search`가 관련 chunk를 반환합니다.
- MCP JSON-RPC endpoint가 allowlist된 tool을 호출합니다.
- `search_law_open_api`가 실제 외부 법률 API 연동 경계를 제공합니다.
- Agent가 bounded reasoning loop로 action을 제안, 검증, 실행하고 반복 제한을 지킵니다.
- Agent가 사용자 facts/question에서 쟁점과 법률 source 후보를 계획하고, 내부 RAG 근거가 부족할 때만 공용 공식 corpus on-demand 보강 후 retrieval을 재실행합니다.
- MVP Agent는 단일 Orchestrator Agent로 동작하며 MCP tool을 Agent로 취급하지 않습니다.
- 후속 멀티에이전트 확장에서는 Supervisor Agent가 전문 Agent 호출 순서와 handoff를 관리합니다.
- `/api/ai/dispute-issues`와 `/api/ai/answer-drafts`가 citation과 disclaimer를 포함해 응답합니다.
- generation run에는 `agent_provider`, `agent_model_name`이 저장됩니다.
- 모든 RAG run에는 `embedding_profile_id`, `embedding_provider`, `embedding_model_name`, `embedding_dimensions`, `prompt_version`, retrieved chunk가 `rag_runs`와 `rag_retrievals`에 저장됩니다.
- Agent run에는 step metadata가 `agent_steps`에 저장됩니다.
- secret 값이 로그, 응답, 문서에 노출되지 않습니다.

## 제출 산출물 체크리스트

과제 제출 전 README 또는 별도 발표 자료에 다음을 정리합니다.

- 서비스 개요와 주요 기능
- 전체 아키텍처
- RAG 아키텍처와 retrieval 평가 결과
- MCP 서버 구조, JSON-RPC 예시, 실제 외부 API tool 설명
- Agent 상태 흐름, tool 선택 방식, loop guard 설명
- 멀티에이전트 확장 시 Supervisor, 전문 Agent, handoff, LangGraph 도입 기준 설명
- 데모 화면 또는 스크린샷
- 한계점과 개선 방향

## 열린 설계 질문

- `AI_RAG_ENABLED=true`로 전환할 때 사용할 기본 active embedding profile은 어떤 provider/model/dimension으로 확정할 것인가요?
- MVP 이후 MCP endpoint를 별도 local process로 분리할 필요가 있는지 운영 복잡도와 과제 요구사항을 기준으로 재검토해야 합니다.
- 국가법령정보 Open API 외에 과제 시연에서 사용할 외부 API 범위는 어디까지로 할 것인가요?
- 업로드된 사용자 문서를 shared corpus에 넣을지, 사용자별 private corpus로 분리할지 결정해야 합니다.
- AI run history는 소유자만 볼 수 있게 할지, admin audit 접근을 허용할지 결정해야 합니다.
- 분쟁 사실관계의 보존 기간은 어떻게 정할 것인가요?
- 답변 초안은 수정 후 게시글로 발행 가능한 형태로 만들지, 별도 artifact로만 유지할지 결정해야 합니다.
- 멀티에이전트 handoff가 복잡해질 때 LangGraph로 이전할 구체적 임계값을 어떻게 정의할 것인가요?

## 참고 문서

- 시스템 아키텍처: `docs/architecture.md`
- API 명세: `docs/api-spec.md`
- 요구사항: `docs/requirements.md`
- DB 설계: `docs/db-design.md`
- Provider adapter 계약: `docs/provider-adapter-spec.md`
- MCP/Agent 설계: `docs/mcp-agent-design.md`
- 보안 및 개인정보 보호: `docs/security-privacy.md`
- RAG pipeline 설계: `docs/rag-pipeline.md`
- 평가 계획: `docs/evaluation-plan.md`
