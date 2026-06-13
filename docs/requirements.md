# 요구사항

## 제품 주제

```text
법률정보 기반 분쟁 쟁점 정리·자료 검색·답변 초안 보조 시스템
```

## 제품 목표

이 시스템은 사용자가 분쟁 사실관계를 정리하고, 후보 법률 쟁점을 파악하며, 관련 법률 자료를 검색하고, citation이 포함된 답변 초안을 작성하도록 돕습니다.

시스템은 최종 생성 결과를 법률 자문으로 표시하지 않습니다.

## 선택한 기술 방향

첫 AI/RAG 구현은 다음 방향을 사용합니다.

- FastAPI 서비스 코드로 명시적 RAG 파이프라인 구현
- PostgreSQL + pgvector로 vector 저장과 유사도 검색 구현
- SQLAlchemy와 Alembic으로 schema와 migration 관리
- MVP의 AI agent/generation과 embedding은 OpenAI API로 시작
- embedding과 LLM generation은 provider adapter로 분리
- Gemini와 Claude는 후속 provider adapter로 확장
- MVP에 MCP 서버, JSON-RPC tool 호출, 실제 외부 법률 API tool 포함
- MVP Agent는 allowlist된 MCP tool을 사용하는 bounded state machine으로 구현
- `AI_RAG_ENABLED=false`인 동안에는 provider key와 model 설정이 비어 있어도 됨
- Next.js UI로 게시판과 AI workflow 제공

LangChain은 첫 RAG milestone의 필수 의존성이 아닙니다. LangGraph도 MVP 필수 의존성으로 두지 않고, 같은 개념을 명시적 bounded state machine으로 구현합니다. MCP는 과제 요구사항이므로 MVP에 포함합니다.

법률 문서 유형의 기본 허용값은 `statute`, `case`, `interpretation`, `admin_appeal`, `user_file`, `memo`로 통일합니다.

## 명시적 RAG를 먼저 구현하는 이유

이 프로젝트는 공동 학습 템플릿입니다. 팀원이 RAG의 각 단계를 직접 확인하고 테스트할 수 있어야 합니다.

- source ingestion
- text normalization
- legal-aware chunking
- embedding
- retrieval
- citation mapping
- prompt construction
- model response handling
- audit persistence

명시적인 FastAPI service 구조를 사용하면 위 단계를 코드에서 직접 추적할 수 있습니다. 이후 프레임워크를 도입하더라도 법률 근거, citation, 감사 기록에 대한 통제권을 유지할 수 있습니다.

## 사용자 유형

### 일반 사용자

- 회원가입 및 로그인
- 게시글과 댓글 작성
- 분쟁 사실관계 입력
- 쟁점 정리, 자료 검색, 답변 초안 보조 요청
- citation과 생성 초안 검토

### 템플릿 개발자

- FastAPI, PostgreSQL, pgvector, RAG, AI service boundary 학습
- 새로운 법률 source 또는 retrieval 전략 추가
- prompt와 retrieval 품질 평가

### 관리자 사용자

아직 구현되어 있지 않지만 이후 단계에서 필요합니다.

- 법률 데이터 ingestion 관리
- 문서 re-index 실행
- 실패한 ingestion job 검토
- prompt version과 source policy 관리

## 비목표

- 최종 법률 자문 제공
- 자격 있는 법률 전문가의 검토 대체
- 첫 버전에서 autonomous multi-agent execution 구현
- 첫 버전에서 real-time crawling 구현
- 결제, 조직 tenant, enterprise SSO 구현

## 기능 요구사항

## FR-001 인증

시스템은 다음을 지원해야 합니다.

- 이메일/비밀번호 회원가입
- 로그인
- 로그아웃
- 현재 사용자 조회
- HttpOnly cookie 기반 인증

수용 기준:

- 인증이 필요한 게시글, 댓글, AI 요청은 로그인 없이는 수행할 수 없습니다.
- 비밀번호는 plaintext로 저장하지 않습니다.
- 인증 cookie 값은 로그에 출력하지 않습니다.

## FR-002 게시판

시스템은 다음을 지원해야 합니다.

- 게시글 목록
- 게시글 상세
- 게시글 생성
- 작성자에 의한 게시글 수정
- 작성자에 의한 게시글 삭제
- Markdown content
- sanitize된 Markdown rendering
- 제목 검색
- pagination

수용 기준:

- 게시글 작성자 권한은 backend에서 검증합니다.
- 공개 작성자 정보에는 email을 포함하지 않습니다.
- Markdown 출력은 frontend에서 sanitize합니다.

## FR-003 댓글

시스템은 다음을 지원해야 합니다.

- 게시글별 댓글 목록
- 댓글 생성
- 작성자에 의한 댓글 수정
- 작성자에 의한 댓글 삭제
- offset/limit pagination

수용 기준:

- 댓글 작성자 권한은 backend에서 검증합니다.
- 댓글 목록은 total count와 pagination metadata를 포함합니다.

## FR-004 태그

시스템은 게시글 content에서 `#태그명` 형식의 태그를 추출해야 합니다.

수용 기준:

- 같은 게시글 안의 중복 태그는 한 번만 저장합니다.
- 태그 이름은 일관되게 정규화합니다.
- 게시글 목록과 상세 응답에 태그를 포함합니다.

## FR-005 법률 source 관리

시스템은 법률 source metadata를 정규화된 문서와 분리해 저장해야 합니다.

초기 source type:

- manual fixture
- user upload
- statute
- case
- legal interpretation
- administrative appeal

수용 기준:

- 각 source는 provider metadata를 가집니다.
- 가능한 경우 각 document는 source URL 또는 source identifier로 추적할 수 있습니다.
- checksum으로 중복 document를 감지할 수 있습니다.

## FR-006 법률 문서 ingestion

시스템은 pasted text, fixture file, 이후 external API로부터 법률 문서를 ingest해야 합니다.

수용 기준:

- raw text를 보존합니다.
- normalized text를 별도로 저장합니다.
- document type, title, case number, statute name, date, source URL 같은 metadata를 보존합니다.
- 업로드 content에서 임의 코드를 실행하지 않습니다.

## FR-007 법률 구조 기반 chunking

시스템은 법률 문서를 retrieval에 적합한 chunk로 분리해야 합니다.

chunking은 다음 구조를 보존해야 합니다.

- 법령 조문 구조
- 항과 호 구조
- 판례 제목
- 주문
- 판시사항 또는 판단 요지
- 이유
- source anchor

수용 기준:

- 각 chunk는 안정적인 `document_id`와 `chunk_index`를 가집니다.
- 각 chunk는 content와 유용한 metadata를 저장합니다.
- AI 응답에서 chunk를 citation으로 참조할 수 있습니다.

## FR-008 Embedding

시스템은 법률 문서 chunk에 대한 vector embedding을 생성해야 합니다.

수용 기준:

- embedding model name은 설정 가능해야 합니다.
- embedding dimension은 설정 가능해야 하며 pgvector column과 일치해야 합니다.
- embedding 실패는 source document를 손상시키지 않고 기록되어야 합니다.
- secret API key는 환경변수에서만 읽고 로그에 남기지 않습니다.

## FR-009 Vector Retrieval

시스템은 pgvector similarity search로 관련 chunk를 검색해야 합니다.

수용 기준:

- 사용자 query에 대해 rank가 매겨진 chunk를 반환합니다.
- 검색 결과는 score, rank, document title, source URL, chunk content를 포함합니다.
- LLM 답변 생성 없이 retrieval만 테스트할 수 있어야 합니다.

## FR-010 Hybrid Retrieval

시스템은 이후 단계에서 hybrid retrieval을 지원해야 합니다.

hybrid retrieval은 다음을 결합합니다.

- vector similarity
- PostgreSQL full-text search
- metadata filter
- optional reranking

수용 기준:

- API는 document type과 date filter를 지원할 수 있어야 합니다.
- retrieval scoring은 디버깅 가능한 수준으로 설명 가능해야 합니다.
- vector-only retrieval은 비교를 위해 유지합니다.

## FR-011 분쟁 쟁점 정리

시스템은 사용자가 제공한 사실관계에서 후보 쟁점을 식별해야 합니다.

수용 기준:

- 출력은 쟁점 제목과 짧은 설명을 포함합니다.
- 출력은 부족한 사실관계 또는 추가 질문을 포함합니다.
- 법률적 주장에는 citation을 포함합니다.
- 법률 자문이 아니라는 disclaimer를 포함합니다.

## FR-012 자료 검색

시스템은 사용자 분쟁과 관련된 법률 자료를 검색해야 합니다.

수용 기준:

- 결과는 cited chunk와 source metadata를 포함합니다.
- 사용자는 검색된 source excerpt를 확인할 수 있습니다.
- 검색 기능은 답변 초안 생성과 독립적으로 동작해야 합니다.

## FR-013 답변 초안 보조

시스템은 사용자 사실관계와 검색된 법률 자료를 기반으로 답변 초안을 생성해야 합니다.

수용 기준:

- 초안에는 citation을 포함합니다.
- 사실관계가 부족하면 한계와 불확실성을 명시합니다.
- 초안에는 법률 자문이 아니라는 disclaimer를 포함합니다.
- 초안은 provider/model metadata, prompt version, retrieved chunk IDs와 함께 저장합니다.

## FR-014 AI run history

시스템은 AI run history를 저장해야 합니다.

수용 기준:

- run은 user ID, query, answer, status, timestamps를 저장합니다.
- generation run은 `agent_provider`, `agent_model_name`을 저장합니다.
- 모든 RAG run은 `embedding_provider`, `embedding_model_name`, `prompt_version`을 저장합니다.
- run은 retrieved chunk IDs와 rank를 저장합니다.
- 사용자는 자신의 과거 run을 조회할 수 있어야 합니다.

## FR-015 Admin ingestion

시스템은 이후 admin-only source ingestion을 지원해야 합니다.

수용 기준:

- 일반 사용자는 global source sync를 실행할 수 없습니다.
- admin 사용자는 document re-index를 실행할 수 있습니다.
- 실패한 ingestion attempt는 admin이 확인할 수 있습니다.

## FR-016 MCP 서버와 외부 tool 연동

시스템은 MVP에서 MCP 서버를 제공하고, Agent가 JSON-RPC 기반 MCP tool을 호출할 수 있어야 합니다.

MVP tool:

- `search_legal_documents`: 내부 pgvector 기반 법률 문서 검색
- `search_law_open_api`: 국가법령정보 Open API 등 실제 외부 법률 API 조회
- `verify_citations`: 생성 초안의 citation 검증

후속 tool:

- `search_precedents`
- `get_law_article`
- `get_board_post`
- `get_board_comments`
- `mask_personal_information`

수용 기준:

- MCP 서버는 JSON-RPC request/response 형식을 사용합니다.
- `tools/list` 또는 이에 준하는 registry는 허용된 tool만 반환합니다.
- `tools/call`은 allowlist에 없는 tool을 거부합니다.
- `search_law_open_api`는 실제 외부 서비스를 호출하되, API key는 서버 환경변수에서만 읽습니다.
- MCP tool input/output은 secret과 raw 개인정보를 제거한 metadata 수준에서 감사 가능해야 합니다.
- tool은 unrestricted filesystem, shell, database operation에 접근할 수 없어야 합니다.
- 외부 API 실패, timeout, rate limit은 안전한 오류로 변환합니다.

## FR-017 AI provider adapter

시스템은 AI provider를 직접 route handler에 결합하지 않고 provider adapter를 통해 호출해야 합니다.

MVP provider:

- agent/generation: OpenAI API
- embedding: OpenAI API

후속 확장 provider:

- Gemini
- Claude
- 테스트용 mock provider

수용 기준:

- provider 선택은 server-side 환경변수로 관리합니다.
- 클라이언트 요청에서 임의 provider를 선택하게 하지 않습니다.
- provider별 API key는 환경변수에서만 읽습니다.
- `AI_RAG_ENABLED=true`일 때는 모든 환경에서 provider key, model, embedding dimension 설정을 검증합니다.
- `AI_AGENT_PROVIDER`와 `AI_EMBEDDING_PROVIDER`를 분리합니다.
- provider 응답은 공통 result schema로 변환합니다.
- generation run에는 `agent_provider`, `agent_model_name`을 저장합니다.
- 모든 RAG run에는 `embedding_provider`, `embedding_model_name`, `prompt_version`을 저장합니다.
- embedding model 또는 dimension 변경 시 DB migration 영향을 검토합니다.

## FR-018 AI Agent orchestration

시스템은 법률 분쟁 쟁점 정리와 답변 초안 생성을 위해 bounded AI Agent를 제공해야 합니다.

MVP Agent 역할:

- 사용자 사실관계와 질문을 바탕으로 검색 계획을 세웁니다.
- allowlist된 MCP tool 중 필요한 tool을 선택하고 호출합니다.
- 내부 RAG 검색 결과와 외부 법률 API 결과를 구분해 관찰합니다.
- 근거 부족, 추가 확인 필요 사실, citation 후보를 정리합니다.
- OpenAI API를 사용해 쟁점 정리 또는 답변 초안을 생성합니다.
- `verify_citations` 결과를 반영해 citation 없는 법률 주장을 제거하거나 한계로 표시합니다.

수용 기준:

- Agent 상태 흐름은 `plan -> call_tool -> observe -> decide -> draft -> verify -> persist`를 기준으로 합니다.
- 각 step은 `agent_steps`에 저장합니다.
- `max_iterations`, `max_tool_calls`, timeout을 설정해 무한 루프를 방지합니다.
- tool 호출 실패 시 run을 실패 처리하거나 근거 부족으로 안전하게 응답합니다.
- 클라이언트는 provider나 tool을 임의 선택할 수 없습니다.
- MVP에서는 OpenAI를 사용하고, Gemini/Claude는 provider adapter 확장으로 추가할 수 있어야 합니다.

## 비기능 요구사항

## NFR-001 보안

시스템은 credential, token, 사용자 사실관계, 법률 source API key를 보호해야 합니다.

요구사항:

- secret 또는 `.env` 값을 출력하지 않습니다.
- 인증 token은 HttpOnly cookie에 저장합니다.
- 상태 변경 요청에는 Origin 검사를 적용합니다.
- production 설정 검증을 강제합니다.
- OpenAI, Gemini, Anthropic, 국가법령정보 Open API key는 secret으로 취급하고 로그에 남기지 않습니다.
- AI endpoint를 외부에 공개하기 전 rate limit을 추가합니다.
- request body size limit을 추가합니다.
- 렌더링되는 Markdown은 sanitize합니다.
- retrieved document는 prompt 안에서 instruction이 아니라 untrusted data로 취급합니다.

## NFR-002 개인정보

분쟁 사실관계에는 개인정보 또는 민감정보가 포함될 수 있습니다.

요구사항:

- 전체 분쟁 사실관계를 그대로 로그에 남기지 않습니다.
- 필요한 사용자 제공 정보만 저장합니다.
- production 전 삭제 또는 보존 정책을 정의합니다.
- 외부 LLM provider로 보내기 전 PII redaction을 고려합니다.

## NFR-003 법률 안전성

생성 결과를 최종 법률 자문처럼 표시해서는 안 됩니다.

요구사항:

- AI 출력에는 disclaimer를 포함합니다.
- 법률 주장에는 citation을 요구합니다.
- 사실 또는 source가 부족하면 불확실성을 표시합니다.
- 실제 분쟁에는 전문가 검토가 필요함을 안내합니다.

## NFR-004 신뢰성

요구사항:

- ingestion은 retry 가능해야 합니다.
- embedding 실패가 document record를 손상시키면 안 됩니다.
- AI provider 실패는 명확한 오류로 반환해야 합니다.
- RAG run은 실패 상태를 기록해야 합니다.

## NFR-005 성능

초기 목표:

- 일반 로컬 개발 환경에서 게시글 목록 응답: 1초 이내
- 작은 학습 dataset의 vector retrieval: 2초 이내
- 답변 초안 생성: provider 의존적이며 UI는 pending 상태를 표시해야 함

이후 목표:

- ingestion과 embedding을 background job으로 분리
- 일정 규모 이상의 dataset에는 vector index 적용
- document와 run history pagination 제공

## NFR-006 재현성

요구사항:

- frontend와 backend dependency version을 고정합니다.
- AI run에는 prompt version과 generation/embedding model metadata를 저장합니다.
- 각 답변에는 retrieved chunk IDs를 저장합니다.
- 반복 가능한 테스트를 위해 fixture document를 사용합니다.

## NFR-007 테스트 가능성

요구사항:

- chunking과 tag extraction을 unit test합니다.
- retrieval query construction을 unit test합니다.
- 작은 fixture dataset으로 RAG search를 integration test합니다.
- embedding과 LLM provider는 테스트에서 mock 처리합니다.
- AI 응답이 citation과 disclaimer를 포함하는지 테스트합니다.

## 권장 프레임워크와 라이브러리

## 유지할 현재 스택

- FastAPI: API layer
- Pydantic: request/response validation
- SQLAlchemy: persistence
- Alembic: migration
- PostgreSQL + pgvector: relational data와 vector data
- Next.js: frontend

## RAG MVP에 추가할 것

- `pgvector` Python package: SQLAlchemy vector 지원
- OpenAI provider adapter 또는 작은 HTTP client wrapper
- Gemini/Claude 확장을 고려한 공통 provider interface
- `httpx`: 외부 법률 API 호출
- deterministic legal document fixture

## 프레임워크 적용 기준

### LangChain

provider 또는 tool integration boilerplate를 줄이는 효과가 명확할 때 도입합니다.

LangChain이 legal document schema, citation model, audit record를 소유하게 두지 않습니다.

### LangGraph

MVP에서는 LangGraph 의존성 없이 명시적 bounded state machine으로 Agent를 구현합니다. 이는 과제에서 요구하는 "LangGraph 또는 유사 구조" 중 유사 구조에 해당합니다.

LangGraph는 workflow가 다음 특성을 갖게 될 때 도입합니다.

- 부족한 사실관계에 대해 사용자에게 추가 질문
- 사용자 답변에 따른 재검색
- human approval
- 실패한 tool retry
- 긴 run의 progress streaming

### MCP

MCP는 MVP 필수 범위입니다. Agent가 내부 RAG와 외부 법률 API를 직접 섞어 호출하지 않도록, `search_legal_documents`, `search_law_open_api`, `verify_citations`를 MCP tool boundary로 노출합니다.

## 학습 중심 구현 순서

권장 학습 경로:

1. 현재 게시판 아키텍처를 이해합니다.
2. RAG table과 migration을 추가합니다.
3. fixture 기반 법률 문서 ingestion을 추가합니다.
4. chunking service를 추가합니다.
5. mock embedding service와 테스트를 추가합니다.
6. pgvector retrieval을 추가합니다.
7. MCP 서버와 tool registry를 추가합니다.
8. `search_legal_documents`, `search_law_open_api`, `verify_citations` tool을 추가합니다.
9. OpenAI 기반 LLM provider adapter를 추가합니다.
10. bounded Agent state machine을 추가합니다.
11. answer draft endpoint를 Agent orchestration에 연결합니다.
12. 쟁점 정리와 자료 검색 UI를 추가합니다.
13. 외부 법률 API ingestion 또는 실시간 조회 정책을 추가합니다.
14. hybrid retrieval을 추가합니다.
15. admin control과 audit view를 추가합니다.
16. Gemini/Claude provider adapter를 필요에 따라 추가합니다.
17. LangChain 또는 LangGraph는 반복 구현 후 필요가 명확할 때 도입합니다.

## 마일스톤

## M1 현재 게시판 안정화

- auth, posts, comments, tags 동작 유지
- frontend dependency version 고정
- backend test 통과 확인
- dependency 설치 후 frontend build 확인

## M2 RAG schema

- legal source, document, chunk, run, retrieval, agent step table 추가
- pgvector vector column 추가
- Alembic migration 추가
- repository test 추가

## M3 Fixture ingestion

- local fixture document ingestion 추가
- normalization과 chunking 추가
- deterministic test 추가

## M4 Vector retrieval

- OpenAI embedding provider adapter 추가
- 테스트용 mock embedding 추가
- pgvector similarity search 추가
- `/api/rag/search` 추가

## M5 Draft assistance

- prompt builder 추가
- OpenAI LLM provider adapter 추가
- MCP server와 tool registry 추가
- `search_legal_documents`, `search_law_open_api`, `verify_citations` tool 추가
- bounded Agent state machine 추가
- `/api/ai/dispute-issues` 추가
- `/api/ai/answer-drafts` 추가
- run, retrieval, agent step 저장

## M6 Legal source integration

- 외부 법률 API client 추가
- MCP `search_law_open_api`에서 실제 외부 API 호출
- source sync command 또는 admin endpoint 추가
- retry와 failure tracking 추가

## M7 품질과 안전성

- rate limiting 추가
- PII policy 추가
- prompt injection test case 추가
- retrieval evaluation fixture 추가
- MCP allowlist, JSON-RPC schema, 외부 API 실패 테스트 추가
- Agent loop guard, tool failure, citation verification 테스트 추가
- admin-only ingestion 적용

## M8 Provider 확장

- Gemini generation provider adapter 추가
- Claude generation provider adapter 추가
- provider별 timeout, error mapping, retry 정책 정리
- provider 변경 시에도 API response와 RAG run schema 유지 확인

## 열린 설계 질문

- `AI_RAG_ENABLED=true`로 전환할 때 사용할 첫 OpenAI embedding model과 dimension은 무엇으로 확정할 것인가요?
- Gemini/Claude를 generation 전용으로 시작한 뒤, provider별 embedding 지원 여부를 언제 확장할 것인가요?
- 업로드된 사용자 문서를 shared corpus에 넣을지, 사용자별 private corpus로 분리할지 결정해야 합니다.
- AI run history는 소유자만 볼 수 있게 할지, admin audit 접근을 허용할지 결정해야 합니다.
- 분쟁 사실관계의 보존 기간은 어떻게 정할 것인가요?
- 어떤 법률 source API가 이용 약관과 프로젝트 정책상 허용되나요?
- 답변 초안은 수정 후 게시글로 발행 가능한 형태로 만들지, 별도 artifact로만 유지할지 결정해야 합니다.

## 참고 자료

- Provider adapter 계약: `docs/provider-adapter-spec.md`
- MCP/Agent 설계: `docs/mcp-agent-design.md`
- 보안 및 개인정보 보호: `docs/security-privacy.md`
- RAG pipeline 설계: `docs/rag-pipeline.md`
- 평가 계획: `docs/evaluation-plan.md`
- Model Context Protocol specification: https://modelcontextprotocol.io/specification/2025-06-18
- MCP tools specification: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LlamaIndex RAG introduction: https://developers.llamaindex.ai/python/framework/understanding/rag/
- pgvector project: https://github.com/pgvector/pgvector
- pgvector Python support: https://github.com/pgvector/pgvector-python
- 국가법령정보 공동활용 Open API guide: https://open.law.go.kr/LSO/openApi/guideList.do
- 판례 목록 조회 API guide: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=precListGuide
