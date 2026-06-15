# 시스템 아키텍처

## 문서 상태

- 대상 브랜치: `project/hyungmin`
- 범위: 현재 게시판 템플릿과 법률정보 RAG 보조 시스템으로 확장하기 위한 목표 아키텍처
- 문서 권한: 이 문서는 아키텍처를 설명합니다. API 상세는 `docs/api-spec.md`, 제품 요구사항은 `docs/requirements.md`, DB 상세는 `docs/db-design.md`, 구현 순서는 `docs/implementation-plan.md`, provider 계약은 `docs/provider-adapter-spec.md`, MCP/Agent 설계는 `docs/mcp-agent-design.md`, 보안/개인정보 정책은 `docs/security-privacy.md`, RAG 세부 흐름은 `docs/rag-pipeline.md`, 평가는 `docs/evaluation-plan.md`를 기준으로 합니다.

## 목적

이 저장소는 기본 게시판 애플리케이션을 기반으로 AI/RAG 기능을 학습하고 확장하기 위한 공동 템플릿입니다.

목표 주제는 다음과 같습니다.

```text
법률정보 기반 분쟁 쟁점 정리·자료 검색·답변 초안 보조 시스템
```

초기 AI 확장은 다음 방향으로 설계합니다.

- FastAPI 백엔드 유지
- PostgreSQL + pgvector 사용
- RAG 파이프라인을 FastAPI 서비스 코드에서 명시적으로 구현
- MVP의 AI agent/generation provider는 OpenAI API 사용
- Gemini와 Claude는 동일한 provider adapter 인터페이스로 이후 확장
- MVP에 MCP 서버, JSON-RPC tool 호출, 실제 외부 법률 API tool을 포함
- MVP Agent는 LangGraph 의존성 없이 bounded state machine으로 구현하고, 복잡도가 커지면 LangGraph로 확장

핵심 목표는 RAG의 각 단계를 팀원이 직접 확인하고 테스트할 수 있게 만드는 것입니다.

## 현재 시스템 개요

현재 구현은 단순 게시판 기능을 갖춘 풀스택 애플리케이션입니다.

### 런타임 구성

```text
Browser
  |
  | HTTP, credentials 포함
  v
Next.js frontend
  |
  | REST API
  v
FastAPI backend
  |
  | SQLAlchemy ORM
  v
PostgreSQL + pgvector extension
```

### 기술 스택

- Frontend: Next.js App Router, React, TypeScript, Tailwind CSS, shadcn 스타일 UI 컴포넌트, Zustand
- Backend: FastAPI, Pydantic, SQLAlchemy, Alembic
- Database: PostgreSQL, `pgvector/pgvector:pg16` 이미지
- Auth: HttpOnly 쿠키 기반 JWT
- Container: Docker Compose (`db`, `migrate`, `backend`, `frontend`)

### 현재 기능

- 이메일/비밀번호 회원가입
- 로그인 및 로그아웃
- HttpOnly JWT 쿠키 기반 인증
- 현재 사용자 조회
- 게시글 CRUD
- Markdown 작성, 미리보기, 표시
- 프론트엔드 Markdown sanitize 렌더링
- `#태그명` 형식 태그 추출
- 게시글 제목 검색과 페이지네이션
- 댓글 작성과 `View more` 방식 페이지네이션

### 현재 테스트 범위

백엔드 테스트는 다음을 확인합니다.

- 회원가입, 로그인, 현재 사용자 조회, 로그아웃
- 이메일 및 닉네임 중복 거부
- 상태 변경 요청의 Origin 검사
- 게시글 CRUD와 작성자 권한
- 태그 추출 및 중복 제거
- 공개 작성자 응답에서 이메일 제외
- 댓글 페이지네이션
- 운영 환경 설정 검증

최근 로컬 확인 결과:

- `backend`에서 `pytest`: 12개 통과
- `frontend`에서 `npm run build`: `node_modules`가 없어 `next` 명령을 찾지 못해 실행되지 않음

## 백엔드 아키텍처

현재 백엔드는 다음 계층 구조를 따릅니다.

```text
backend/app/
  api/             FastAPI 라우터와 요청 의존성
  services/        비즈니스 로직, 권한 검사, 트랜잭션 처리
  repositories/    데이터베이스 조회와 저장
  models/          SQLAlchemy ORM 모델
  schemas/         Pydantic 요청/응답 스키마
  core/            설정, 데이터베이스, 보안 유틸리티
```

### 의존성 방향

의도한 의존성 방향은 다음과 같습니다.

```text
api -> services -> repositories -> models
api -> schemas
services -> schemas, repositories, models, core
repositories -> models
core -> external libraries
```

컨트롤러는 얇게 유지해야 합니다. 비즈니스 규칙은 서비스에 두고, 직접적인 데이터베이스 접근은 리포지토리에 둡니다. AI/RAG 기능이 추가되면 검색, 근거 검증, 프롬프트 구성, 감사 기록 같은 로직이 많아지므로 이 계층 분리가 더 중요해집니다.

### 현재 백엔드 구조 평가

- `api/auth.py`, `api/posts.py`, `api/comments.py`, `api/tags.py`는 대체로 서비스 계층에 처리를 위임합니다.
- `api/deps.py`는 현재 인증 사용자 조회 과정에서 `repositories/users.py`를 직접 사용합니다. 의존성 헬퍼로는 허용 가능한 수준이지만, 더 엄격하게 보려면 `services/auth.py`로 이동할 수 있습니다.
- 현재 서비스 계층이 트랜잭션 커밋을 담당합니다. 현재 규모에서는 단순하고 적절합니다.
- SQLAlchemy 세션은 동기 방식입니다. 게시판과 초기 RAG MVP에는 충분합니다.
- 대용량 문서 수집, 임베딩, 외부 API 동기화는 요청 핸들러 안에서 직접 수행하지 않아야 합니다.

## 프론트엔드 아키텍처

프론트엔드는 화면, API 클라이언트, 상태 저장소, 컴포넌트로 나뉩니다.

```text
frontend/src/
  app/          Next.js App Router 페이지
  screens/      페이지 단위 client component
  api/          타입이 지정된 REST API 클라이언트
  stores/       Zustand 상태 저장소
  components/   UI 및 기능 컴포넌트
  types.ts      공통 TypeScript 타입
```

현재 API 호출은 `fetch`에서 `credentials: "include"`를 사용합니다. 이는 백엔드의 HttpOnly 쿠키 인증 설계와 맞습니다.

AI/RAG 기능도 같은 패턴을 따릅니다.

- `frontend/src/api/` 아래에 타입이 지정된 API 함수를 추가합니다.
- `frontend/src/screens/` 아래에 AI/RAG 화면 컴포넌트를 추가합니다.
- LLM 프롬프트, 도구 실행, citation 처리, 검색 로직은 프론트엔드에 두지 않습니다.

## 현재 데이터 모델

### 테이블

```text
users
  id
  email unique
  password_hash
  nickname unique
  created_at
  updated_at

posts
  id
  author_id -> users.id
  title
  content
  created_at
  updated_at

comments
  id
  post_id -> posts.id
  author_id -> users.id
  content
  created_at
  updated_at

tags
  id
  name unique

post_tags
  post_id -> posts.id
  tag_id -> tags.id
```

### pgvector 상태

Alembic migration `0002_enable_pgvector.py`는 PostgreSQL `vector` 확장을 활성화합니다. 그러나 아직 vector 컬럼이나 RAG용 테이블은 없습니다.

즉, 현재 상태는 RAG 기반이 준비된 수준이며 실제 문서 저장, chunk 저장, embedding 저장, 검색 실행 모델은 추가 구현이 필요합니다.

## 목표 AI/RAG 아키텍처

첫 AI 확장은 프레임워크 내부에 검색 과정을 숨기지 않고, 명시적인 RAG 서비스 구조로 구현합니다.

```text
Browser
  |
  v
Next.js AI/RAG screens
  |
  v
FastAPI api/rag.py, api/ai.py, api/mcp.py, api/legal_documents.py
  |
  v
AI/RAG services
  |
  +-- ingestion service
  +-- chunking service
  +-- embedding service
  +-- retrieval service
  +-- citation service
  +-- prompt service
  +-- answer draft service
  |
  v
repositories
  |
  v
PostgreSQL tables + pgvector indexes
  |
  v
LLM provider and external legal-data APIs
```

### 제안 백엔드 패키지 구조

```text
backend/app/
  api/
    ai.py
    legal_documents.py
  services/
    ai/
      client.py
      providers/
        base.py
        openai.py
        gemini.py
        anthropic.py
    rag/
      ingestion.py
      chunking.py
      embeddings.py
      retrieval.py
      citations.py
      prompts.py
      answer_drafts.py
    legal_sources.py
  repositories/
    legal_documents.py
    document_chunks.py
    embeddings.py
    rag_runs.py
  models/
    legal_document.py
    document_chunk.py
    embedding.py
    rag_run.py
  schemas/
    ai.py
    legal_document.py
```

이 파일들을 한 번에 모두 만들 필요는 없습니다. 기능을 구현하는 순서에 맞춰 작게 추가합니다.

### 명시적 RAG 파이프라인

```text
1. Source acquisition
   - 법률 원천 자료를 가져오거나 업로드합니다.
   - 원천 메타데이터와 원문을 저장합니다.

2. Normalization
   - HTML, XML, PDF, text를 정규화된 plain text로 변환합니다.
   - 출처 ID, 날짜, 문서 유형, 조문 번호, 사건번호, URL을 보존합니다.

3. Chunking
   - 문서를 검색 가능한 chunk로 분리합니다.
   - 법령, 조문, 항, 호, 판례 제목, 주문, 이유 등 법률 문서 구조를 보존합니다.
   - chunk 순서와 출처 anchor를 저장합니다.

4. Embedding
   - chunk별 embedding을 생성합니다.
   - vector는 chunk row가 아니라 embedding profile별 row에 저장합니다.
   - embedding provider, model, dimension, distance metric은 `embedding_profiles`로 관리합니다.
   - 같은 chunk가 여러 embedding profile을 가질 수 있지만, 검색 시에는 하나의 profile만 선택해 비교합니다.

5. Retrieval
   - 사용자 query를 embedding합니다.
   - vector similarity로 top-k chunk를 조회합니다.
   - `focused_answer`와 `issue_spotting` 검색 모드를 구분하고, `score_threshold`, `max_chunks_per_document`로 결과 폭과 문서 편중을 조절합니다.
   - 문서 유형, 날짜, 법원, 법령명, jurisdiction 같은 metadata filter를 적용할 수 있게 합니다.
   - 이후 단계에서 vector search와 PostgreSQL full-text search를 결합한 hybrid search를 도입합니다.

6. MCP tool exposure
   - 내부 retrieval은 `search_legal_documents` MCP tool로도 호출할 수 있게 합니다.
   - 국가법령정보 Open API 조회는 `search_law_open_api` MCP tool로 호출합니다.
   - `search_law_open_api`의 `target`은 내부 `document_type`인 `statute`, `case`, `interpretation`, `admin_appeal`을 사용하고, 외부 API별 parameter는 adapter 내부에서 매핑합니다.
   - citation 검증은 `verify_citations` MCP tool로 분리합니다.
   - MCP tool은 allowlist와 JSON-RPC schema로 제한합니다.

7. Reranking and filtering
   - 먼저 deterministic filter를 적용합니다.
   - 필요 시 재정렬 로직이나 모델 기반 rerank를 적용합니다.
   - 낮은 신뢰도이거나 오래된 근거를 제거합니다.

8. Agent orchestration
   - Agent는 bounded state machine으로 tool 선택, 관찰, 초안 작성, citation 검증을 수행합니다.
   - MVP의 상태 흐름은 `plan -> call_tool -> observe -> decide -> draft -> verify -> persist`입니다.
   - `max_iterations`와 `max_tool_calls`로 무한 루프를 방지합니다.

9. Prompt assembly
   - 사용자 사실관계, 검색된 chunk, 답변 규칙을 조합해 prompt를 구성합니다.
   - 법률적 주장에는 citation을 요구합니다.
   - 근거가 부족하면 불확실성을 명시하게 합니다.

10. Draft generation
   - 쟁점 요약, 자료 검색 결과, 답변 초안을 생성합니다.
   - citation과 법률 자문이 아니라는 고지를 포함합니다.

11. Persistence and audit
   - query, retrieved chunk IDs, Agent step, MCP tool call metadata, prompt version, provider/model metadata, draft, 사용자 action을 저장합니다.
   - secret, 인증 쿠키, raw JWT는 저장하거나 로그에 남기지 않습니다.
```

## 제안 RAG 데이터 모델

초기 구현 목표로 다음 스키마를 권장합니다.

```text
legal_sources
  id
  provider                 -- 예: law_open_api, scourt, upload, fixture
  source_type              -- statute, case, interpretation, admin_appeal, user_file, memo
  external_id              -- provider 쪽 식별자
  source_url
  fetched_at
  metadata_json
  created_at
  updated_at

legal_documents
  id
  source_id -> legal_sources.id
  document_type            -- statute, case, interpretation, admin_appeal, user_file, memo
  title
  canonical_id             -- 법령 ID, 사건번호, 내부 ID
  version_label            -- 시행일, 선고일, 업로드 버전
  published_date
  effective_date
  raw_text
  normalized_text          -- normalization 전에는 null 가능
  raw_checksum
  normalized_checksum      -- normalization 전에는 null 가능
  dedup_status             -- unique, duplicate, superseded 등
  conflict_status          -- none, review_required, resolved 등
  duplicate_of_document_id -> legal_documents.id nullable
  index_status
  indexed_at
  index_error
  created_at
  updated_at

legal_document_chunks
  id
  document_id -> legal_documents.id
  chunk_index
  heading
  content
  token_count
  metadata_json            -- 조문 번호, 항, 법원, 사건번호 등
  created_at
  updated_at

embedding_profiles
  id
  provider                 -- openai, mock, anthropic, voyage 등
  model_name
  dimensions
  distance_metric          -- cosine, l2, inner_product 등
  vector_type              -- vector, halfvec 등
  status                   -- active, deprecated, retired
  is_default
  metadata_json
  created_at
  updated_at

legal_document_chunk_embeddings
  id
  chunk_id -> legal_document_chunks.id
  embedding_profile_id -> embedding_profiles.id
  embedding vector
  embedding_status         -- pending, embedded, failed, stale
  embedded_at
  embedding_error
  content_checksum
  metadata_json
  created_at
  updated_at

rag_runs
  id
  user_id -> users.id
  run_type                  -- search, dispute_issues, answer_draft, agent_run
  query
  facts
  status                   -- pending, completed, failed
  answer
  disclaimer
  agent_provider           -- generation run이 아니면 null 가능
  agent_model_name         -- generation run이 아니면 null 가능
  embedding_profile_id
  embedding_provider
  embedding_model_name
  embedding_dimensions
  prompt_version
  error_code
  error_message
  created_at
  updated_at

agent_steps
  id
  rag_run_id -> rag_runs.id
  step_index
  step_type                 -- plan, tool_call, tool_result, decide, draft, verify, error
  tool_name                 -- MCP tool 이름. tool 호출이 아니면 null 가능
  status                   -- pending, completed, failed, skipped
  input_json                -- secret을 제거한 입력 metadata
  output_json               -- secret을 제거한 출력 metadata
  error_code
  error_message
  started_at
  finished_at
  created_at

rag_retrievals
  id
  rag_run_id -> rag_runs.id
  chunk_id -> legal_document_chunks.id
  chunk_embedding_id -> legal_document_chunk_embeddings.id nullable
  embedding_profile_id -> embedding_profiles.id nullable
  rank
  score
  retrieval_type           -- vector, keyword, hybrid, manual
  created_at
```

구현 참고:

- embedding 모델과 vector dimension은 `embedding_profiles`로 관리합니다. 환경변수는 기본 profile 선택 또는 생성에만 사용합니다.
- vector index는 실제 chunk embedding 데이터가 들어간 뒤 profile별 partial/expression index로 생성하는 편이 좋습니다.
- 서로 다른 provider/model/dimension profile의 vector를 같은 검색 공간에서 직접 비교하지 않습니다.
- 첫 단계는 vector-only retrieval로 시작하고, 이후 PostgreSQL full-text search를 결합합니다.
- 법률 답변은 추적 가능해야 하므로 원천 metadata를 반드시 보존합니다.
- 법률 문서 중복 판단은 `checksum` 단독 기준으로 하지 않습니다. `raw_checksum`, `normalized_checksum`, `canonical_id`, `version_label`, `effective_date`를 함께 사용합니다.
- 같은 법령의 다른 시행일 또는 version은 별도 문서로 보존합니다. 최신본만 남기고 과거 버전을 삭제하면 분쟁 발생 시점의 근거를 잃을 수 있습니다.
- 같은 canonical/version인데 normalized checksum이 다르면 자동 병합하거나 삭제하지 않고 conflict review 상태로 저장합니다.

## 법률 데이터 소스

법률 데이터는 공식 법률 corpus와 사용자 제공 문서를 구분합니다.

- 공식 법률 corpus: 법령, 판례, 법령해석례, 행정심판례 등입니다. 사용자가 직접 원문을 업로드하지 않고 backend가 국가법령정보 Open API 또는 이용 조건이 명확한 공공 API에서 수집합니다. `provider=law_open_api` 같은 공식 provider metadata를 보존합니다.
- 사용자 제공 문서: 계약서, PDF, 스캔본, 사용자가 직접 입력한 메모 등입니다. `document_type=user_file` 또는 `memo`로 저장하고, 공식 법령 원문처럼 최종 진실로 간주하지 않습니다.
- 테스트와 학습 재현성을 위한 fixture 문서는 `provider=fixture`로 저장합니다.

공식 법률 corpus는 매번 전문을 다시 내려받지 않습니다. backend는 먼저 국가법령정보 Open API의 metadata 응답에서 `provider`, `external_id`, `canonical_id`, `version_label`, `effective_date`, `published_date`를 추출하고, DB의 기존 `legal_sources`, `legal_documents`, `legal_document_chunks`, `legal_document_chunk_embeddings` 상태와 비교합니다. 같은 canonical/version 문서가 이미 indexed 상태이고 선택된 embedding profile의 chunk embedding이 최신이면 전문 API 호출, normalization, chunking, embedding 호출을 생략하고 DB의 기존 chunk/embedding을 재사용합니다.

새 시행일이나 새 version이 확인되면 기존 문서를 덮어쓰지 않고 별도 문서 version으로 저장합니다. 반대로 같은 canonical/version인데 전문 재조회 결과 `normalized_checksum`이 달라지면 어떤 것이 최종 진실인지 자동 판단하지 않고 conflict review 상태로 남깁니다. 최신성 확인은 기존 색인을 안전하게 재사용하기 위한 절차이며, 과거 version 삭제 기준이 아닙니다.

초기 소스 도입 순서는 다음을 권장합니다.

1. 테스트와 학습 재현성을 위한 fixture 문서
2. 사용자 제공 텍스트 또는 계약서/PDF 추출 텍스트 ingestion
3. 법령, 판례, 법령해석례, 행정심판례 등 국가법령정보 Open API
4. 이용 조건과 접근 정책이 명확한 법원 또는 공공데이터 API

이용 약관을 확인하지 않은 웹사이트 scraping은 피합니다. API key는 환경변수로 관리하고 값은 로그에 남기지 않습니다.

## AI Provider 경계

LLM provider는 라우터에서 직접 호출하지 않습니다.

권장 호출 경계는 다음과 같습니다.

```text
services/rag/answer_drafts.py
  -> services/rag/prompts.py
  -> services/rag/retrieval.py
  -> services/ai/client.py
  -> services/ai/providers/{provider}.py
```

MVP에서는 `AI_AGENT_PROVIDER=openai`를 기본값으로 사용하고 OpenAI API adapter를 먼저 구현합니다. Gemini와 Claude는 같은 인터페이스를 구현하는 provider adapter로 추가합니다.

권장 provider 설정:

```text
AI_RAG_ENABLED=false
AI_AGENT_PROVIDER=openai
AI_EMBEDDING_PROVIDER=openai
AI_AGENT_MODEL=<server-selected-model>
AI_EMBEDDING_MODEL=<server-selected-embedding-model>
AI_EMBEDDING_DIMENSIONS=<vector-dimension>
AI_REQUEST_TIMEOUT_SECONDS=60
OPENAI_API_KEY=<secret>
OPENAI_BASE_URL=<optional-compatible-endpoint>
GEMINI_API_KEY=<secret, optional>
GEMINI_BASE_URL=<optional-compatible-endpoint>
ANTHROPIC_API_KEY=<secret, optional>
ANTHROPIC_BASE_URL=<optional-compatible-endpoint>
```

`AI_RAG_ENABLED=false`인 동안에는 실제 provider key와 model 설정이 비어 있어도 됩니다. AI/RAG 기능을 활성화하기 전에 실제 `.env`에 `OPENAI_API_KEY`, `AI_AGENT_MODEL`, `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_DIMENSIONS`를 채워야 합니다. `AI_RAG_ENABLED=true`인 모든 환경에서는 설정 검증 실패 시 애플리케이션이 빠르게 중단되어야 합니다.

`services/ai/client.py`는 provider별 SDK 차이를 숨기고 구조화된 결과를 반환해야 합니다. 이렇게 하면 OpenAI에서 시작하더라도 Gemini, Claude, mock provider, 추후 LangChain 도입이 API route와 RAG service에 영향을 주지 않습니다.

초기 공통 인터페이스 예시는 다음과 같습니다.

```text
generate(prompt, *, model, timeout) -> AITextResult
embed(texts, *, model, dimensions, timeout) -> list[EmbeddingResult]
```

주의할 점:

- agent/generation provider와 embedding provider는 분리합니다.
- Claude는 generation provider로 확장할 수 있지만, embedding provider로 사용할 수 있다고 가정하지 않습니다. 다만 `embedding_profiles.provider`는 향후 Anthropic 또는 호환 provider가 embedding을 지원할 경우 schema 변경 없이 수용할 수 있게 문자열로 둡니다.
- embedding dimension은 `embedding_profiles.dimensions`와 provider 응답 vector 길이가 일치해야 합니다. 모델 변경 시 기존 profile을 덮어쓰지 않고 새 profile을 생성해 재임베딩합니다.
- provider API key는 환경변수에서만 읽고 로그에 남기지 않습니다.

## MCP와 Agent 위치

과제 요구사항을 충족하기 위해 MCP와 AI Agent는 MVP 범위에 포함합니다.

MCP는 모델에게 unrestricted database, filesystem, shell 접근을 제공하기 위한 장치가 아닙니다. 이 프로젝트에서 MCP는 Agent가 사용할 수 있는 법률 조회와 검증 tool의 표준 경계입니다. MVP에서는 FastAPI 내부 `POST /api/mcp` endpoint로 제공하고, 모든 tool은 서버 allowlist와 JSON-RPC request/response schema로 제한합니다. 별도 local MCP process는 후속 확장 후보입니다.

MVP MCP tool:

- `search_legal_documents`: 내부 pgvector 기반 RAG 검색을 호출합니다.
- `search_law_open_api`: 국가법령정보 Open API 등 실제 외부 법률 API를 호출합니다.
- `verify_citations`: 초안의 citation이 해당 run에서 검색된 chunk 또는 외부 source metadata에 근거하는지 검증합니다.

MVP Agent 책임:

- 사용자 사실관계와 질문을 바탕으로 필요한 검색 계획을 세웁니다.
- allowlist된 MCP tool 중 필요한 tool만 호출합니다.
- tool 결과를 관찰하고 근거 부족 여부를 판단합니다.
- OpenAI API를 사용해 쟁점 정리 또는 답변 초안을 생성합니다.
- citation 검증을 통과한 결과만 사용자에게 반환합니다.
- 각 step을 `agent_steps`에 저장하고 `max_iterations`, `max_tool_calls`, timeout으로 무한 루프를 방지합니다.

LangGraph는 MVP 필수 의존성으로 두지 않습니다. 대신 위 상태 흐름을 명시적 bounded state machine으로 구현합니다. 이후 분기, 재시도, human-in-the-loop, 장기 실행 workflow가 복잡해지면 같은 상태 모델을 LangGraph graph로 옮길 수 있습니다.

## 보안 아키텍처

### 현재 보안 제어

- 비밀번호는 Passlib bcrypt로 hash합니다.
- JWT는 HttpOnly cookie에 저장합니다.
- 상태 변경 메서드는 허용된 `Origin` header를 요구합니다.
- CORS는 설정된 frontend origin만 허용합니다.
- production 설정은 기본 JWT secret, HTTP origin, localhost origin, insecure auth cookie를 거부합니다.
- production에서는 FastAPI docs endpoint를 비활성화합니다.
- Markdown은 프론트엔드에서 sanitize 후 렌더링합니다.

### AI/RAG에 필요한 추가 보안

- auth 및 AI endpoint rate limiting
- upload 및 prompt request size limit
- 사용자 분쟁 사실관계에 대한 개인정보 처리 정책
- AI run과 사용된 source chunk에 대한 audit log
- MCP tool call과 Agent step에 대한 audit log
- prompt injection 방어: 검색된 문서는 instruction이 아니라 data로 취급
- 법률 주장에는 citation 요구
- "법률 자문이 아닌 초안 보조" disclaimer
- role 도입 후 ingestion endpoint는 admin-only
- ingestion과 embedding은 background job으로 분리
- model version과 prompt version 추적
- `rag_retrievals` 저장을 통한 검색 재현성 확보
- MCP tool allowlist, 외부 API timeout, tool call rate limit

## 운영 아키텍처

### 로컬 개발

- PostgreSQL은 Docker Compose로 실행합니다.
- FastAPI와 Next.js는 hot reload를 위해 로컬에서 실행합니다.
- 필요한 환경변수 목록은 `.env.example`을 기준으로 합니다.
- `.env`는 절대 commit하지 않습니다.

### 설정 그룹

`.env.example`의 설정은 다음 그룹으로 관리합니다. 값은 환경별 `.env`에서 주입하고, secret 값은 로그나 문서에 출력하지 않습니다.

- App/runtime: `APP_ENV`
- Database: `DATABASE_URL`
- Auth/JWT: `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `AUTH_COOKIE_SECURE`
- Frontend/API origin: `FRONTEND_ORIGIN`, `NEXT_PUBLIC_API_BASE_URL`
- Local Docker database: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- AI/RAG: `AI_RAG_ENABLED`, `AI_AGENT_PROVIDER`, `AI_EMBEDDING_PROVIDER`, `AI_AGENT_MODEL`, `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_DIMENSIONS`, `AI_REQUEST_TIMEOUT_SECONDS`, `AI_AGENT_MAX_ITERATIONS`, `AI_AGENT_MAX_TOOL_CALLS`, `RAG_TOP_K`, `RAG_PROMPT_VERSION`
- MCP: `MCP_SERVER_ENABLED`, `MCP_ALLOWED_TOOLS`, `MCP_REQUEST_TIMEOUT_SECONDS`
- Provider credentials/endpoints: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `GEMINI_API_KEY`, `GEMINI_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `LAW_OPEN_API_OC`

### 백그라운드 작업

다음 조건 중 하나라도 해당하면 RAG ingestion과 embedding은 background worker로 분리해야 합니다.

- 외부 API에서 문서를 수집합니다.
- 업로드 파일이 커질 수 있습니다.
- embedding 호출이 request timeout을 넘길 수 있습니다.
- retry와 backoff가 필요합니다.

학습 단계에서는 FastAPI 관리용 script나 command로 충분합니다. 더 커지면 Celery, RQ, Arq 같은 worker를 고려합니다.

### 관측성과 로그

구조화 로그에 남길 항목:

- request ID
- 가능한 경우 user ID
- AI run ID
- source provider
- retrieved chunk IDs
- provider/model metadata
- latency
- failure reason

로그에 남기지 말아야 할 항목:

- secret
- auth cookie
- raw JWT
- 전체 private dispute facts

## 설계상 보완 필요 사항

### 1. RAG schema가 아직 없습니다

현재 DB는 pgvector extension만 활성화합니다. AI endpoint를 만들기 전에 source, document, chunk, run, retrieval 테이블을 추가해야 합니다.

### 2. AI 호출은 controller에 두면 안 됩니다

라우터는 얇게 유지합니다. retrieval, prompt 구성, provider 호출, citation, persistence는 service 계층에 둡니다.

### 3. 인증에 token revocation 또는 refresh 설계가 없습니다

현재 short-lived access token cookie는 단순하고 학습용으로 적절합니다. 법률/AI 기능이 민감해지면 refresh token, session table, token versioning, server-side session invalidation을 고려해야 합니다.

### 4. Rate limiting이 없습니다

auth와 AI endpoint는 비용과 보안 위험이 있으므로 외부 공개 전 rate limiting이 필요합니다.

### 5. Role 모델이 없습니다

현재는 일반 사용자만 있습니다. RAG ingestion, source sync, prompt/template 관리는 role 도입 후 admin-only로 제한해야 합니다.

### 6. Frontend dependency가 `latest`입니다

공동 템플릿에서는 재현성을 위해 frontend dependency version을 고정하는 것이 좋습니다.

### 7. Origin 검사가 엄격합니다

상태 변경 요청은 설정된 `Origin`이 없으면 거부됩니다. 브라우저 보호에는 적절하지만, non-browser API client와 테스트는 허용 origin header를 넣어야 합니다.

### 8. 검색이 제목 검색에 한정됩니다

현재 게시글 검색은 title `ilike`입니다. 법률 검색은 별도 document chunk, vector search, metadata filter, full-text search가 필요합니다.

### 9. MCP 서버와 외부 API tool이 필요합니다

과제 요구사항상 MCP 서버, JSON-RPC request/response, 실제 외부 서비스 연동이 필요합니다. MVP에서는 `search_law_open_api`로 국가법령정보 Open API를 호출하고, tool 호출 metadata를 audit에 남겨야 합니다.

### 10. Agent workflow persistence와 loop guard가 필요합니다

쟁점 추출, retrieval, MCP tool 호출, draft 생성, citation 검증, 사용자 검토는 단순 응답으로 끝내지 말고 `rag_runs`와 `agent_steps`로 저장해야 합니다. Agent는 `max_iterations`, `max_tool_calls`, timeout, 실패 상태 저장을 반드시 가져야 합니다.

### 11. AI provider 설정은 Docker Compose 전달도 필요합니다

`.env.example`에는 AI provider 관련 변수를 추가하지만, 실제 Docker 실행에서 backend container가 해당 값을 읽으려면 `docker-compose.yml`의 backend와 migrate 환경변수 전달도 함께 정리해야 합니다. AI 구현 단계에서 누락하지 않아야 합니다.

## 프레임워크 결정

초기 구현은 FastAPI service + pgvector 기반 명시적 RAG 구조를 사용합니다. MCP 서버와 bounded Agent state machine은 과제 요구사항을 충족하기 위해 MVP에 포함합니다.

권장 진행 순서:

1. FastAPI에서 deterministic RAG service를 직접 구현합니다.
2. OpenAI API 기반 generation/embedding provider adapter를 추가합니다.
3. MCP 서버와 allowlist된 tool registry를 추가합니다.
4. `search_legal_documents`, `search_law_open_api`, `verify_citations` tool을 구현합니다.
5. bounded Agent state machine으로 tool 선택, 실행, 관찰, 초안 작성, 검증을 구현합니다.
6. hybrid retrieval과 citation tracking을 추가합니다.
7. Gemini와 Claude provider adapter는 동일 인터페이스로 후속 추가합니다.
8. LangChain은 provider/tool integration code를 줄이는 효과가 분명할 때만 도입합니다.
9. LangGraph는 workflow가 durable multi-step orchestration, branching, retry, human-in-the-loop를 요구할 때 도입합니다.

이 접근은 법률 근거 데이터 모델을 프레임워크에 너무 일찍 종속시키지 않으면서도, 과제의 MCP/Agent 요구사항과 학습 경로, 디버깅 가능성을 함께 만족시킵니다.

## 참고 자료

- MCP/Agent 설계: `docs/mcp-agent-design.md`
- Provider adapter 계약: `docs/provider-adapter-spec.md`
- Model Context Protocol specification: https://modelcontextprotocol.io/specification/2025-06-18
- MCP tools specification: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LlamaIndex RAG introduction: https://developers.llamaindex.ai/python/framework/understanding/rag/
- pgvector project: https://github.com/pgvector/pgvector
- pgvector Python support: https://github.com/pgvector/pgvector-python
- 국가법령정보 공동활용 Open API guide: https://open.law.go.kr/LSO/openApi/guideList.do
