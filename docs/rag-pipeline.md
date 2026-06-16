# RAG Pipeline 설계

## 목적

이 문서는 법률정보 기반 RAG 파이프라인의 단계별 책임과 입출력 계약을 정의합니다.

MVP는 FastAPI service 코드로 명시적으로 구현합니다. MCP 서버와 단일 Orchestrator Agent 기반 bounded reasoning loop/state machine은 과제 요구사항을 충족하기 위해 포함하며, LangChain과 LangGraph는 초기 필수 의존성으로 두지 않습니다. 멀티에이전트 workflow는 단일 Orchestrator가 안정화된 뒤 Supervisor Agent와 전문 Agent 구조로 확장합니다.

## 전체 흐름

```text
source 수집
  -> normalization
  -> legal-aware chunking
  -> embedding
  -> vector retrieval
  -> MCP tool exposure
  -> bounded Agent orchestration
  -> optional filtering/reranking
  -> prompt assembly
  -> generation
  -> citation validation
  -> persistence/audit
```

사용자 요청 처리 흐름에서는 `vector retrieval` 앞에 Orchestrator LLM의 `issue/source planning`이 먼저 실행됩니다. 내부 검색 근거가 부족하면 공식 source on-demand sync와 embedding을 수행한 뒤 retrieval을 다시 실행합니다.

## 1. Source 수집

입력:

- fixture text
- pasted text
- user upload. 계약서, PDF, 스캔본, 메모 같은 사용자 제공 문서입니다.
- 국가법령정보 Open API 응답
- 추후 법원/공공데이터 API 응답

출력:

- `legal_sources`
- `legal_documents`

저장할 metadata:

- provider
- source type
- external ID
- source URL
- fetched_at
- title
- document type
- published/effective date
- raw checksum
- normalized checksum
- dedup status
- conflict status

규칙:

- 이용 약관을 확인하지 않은 scraping은 하지 않습니다.
- API key는 환경변수에서만 읽습니다.
- `raw_checksum`은 수집 원문 기준, `normalized_checksum`은 정규화 text 기준으로 계산합니다.
- `checksum` 단독 비교로 최종 중복 여부를 판단하지 않습니다.
- `document_type`, `canonical_id`, `version_label` 또는 `effective_date`, `normalized_checksum`을 함께 사용해 중복과 버전을 구분합니다.
- 같은 canonical/version인데 `normalized_checksum`이 같으면 `dedup_status=duplicate`로 원본 문서를 참조합니다.
- 같은 canonical/version인데 `normalized_checksum`이 다르면 자동 삭제하지 않고 `conflict_status=review_required`로 저장합니다.
- `effective_date` 또는 `version_label`이 다르면 같은 법령 또는 문서의 다른 버전으로 보존합니다.
- `source_type`과 `document_type`의 기본 허용값은 `statute`, `case`, `interpretation`, `admin_appeal`, `user_file`, `memo`로 맞춥니다.
- 법령, 판례, 법령해석례, 행정심판례 같은 공식 법률 corpus는 사용자가 원문을 업로드하지 않고 backend가 국가법령정보 Open API 또는 허용된 공공 API에서 수집합니다.
- 사용자 제공 계약서, PDF 추출 텍스트, 스캔본 OCR 결과, 직접 입력 메모는 `document_type=user_file` 또는 `memo`로 저장합니다.
- pasted text와 사용자 확인을 거친 업로드 추출 텍스트는 `legal_sources.provider=upload`, fixture는 `legal_sources.provider=fixture`, 국가법령정보 Open API 수집 자료는 `legal_sources.provider=law_open_api`로 저장합니다.
- frontend가 PDF text extraction을 수행할 수는 있지만, 이는 미리보기와 사용자 확인을 위한 전처리입니다. 최종 normalization, checksum, duplicate/conflict 판정, chunking은 backend가 단일 기준으로 수행합니다.

사용자 요청 기반 공식 corpus 보강 흐름:

```text
사용자 스토리/질문 입력
  -> Orchestrator LLM의 issue/source planning
  -> 내부 RAG 검색
  -> 근거 부족 시 공식 source metadata 조회
  -> 요청 한도 안에서 on-demand sync + chunking + embedding
  -> 내부 RAG 재검색
  -> 답변 초안
  -> citation 검증
  -> 응답
```

issue/source planning 출력:

```text
issues[]
legal_domains[]
candidate_statutes[]
rag_queries[]
external_source_queries[]
missing_facts[]
```

planning 규칙:

- `candidate_statutes`와 `external_source_queries`는 검색 계획이며, 그 자체가 citation 가능한 근거가 아닙니다.
- citation 가능한 evidence는 내부 retrieval로 선택된 chunk 또는 공식 source metadata 검증을 통과한 결과로 제한합니다.
- 공식 법률 corpus는 사용자별 embedding으로 만들지 않고 공용 `legal_sources`, `legal_documents`, `legal_document_chunks`, `legal_document_chunk_embeddings`로 저장합니다.
- 사용자 계약서, PDF, 메모는 사용자 또는 tenant 범위의 private corpus로 남기며 다른 사용자 요청의 공용 근거로 사용하지 않습니다.
- on-demand sync는 요청당 후보 문서 수, provider timeout, API quota, rate limit을 적용합니다.
- `conflict_status=review_required` 또는 `index_status=failed` 문서는 검색 결과와 citation 후보에서 제외합니다.
- 새 chunk embedding이 준비되면 같은 요청에서 내부 RAG 검색을 다시 수행해야 합니다.

국가법령정보 Open API preflight 흐름:

```text
metadata API 조회
  -> provider, external_id, canonical_id, version_label, effective_date, published_date 추출
  -> DB의 legal_sources + legal_documents 조회
  -> 같은 canonical/version 문서가 indexed 상태이고 선택 embedding profile의 chunk embedding이 최신이면 전문 API 호출 생략
  -> 없거나 새 version이면 전문 API 호출 후 ingestion
  -> 같은 canonical/version인데 checksum이 달라지면 conflict review로 저장
```

preflight 규칙:

- 전문 API를 호출하기 전에 metadata API로 법령명, 법령 ID, 시행일, 공포일, 개정 식별자, source URL을 먼저 확인합니다.
- metadata 조회 결과는 `legal_sources.provider`, `legal_sources.external_id`, `legal_sources.metadata_json`과 `legal_documents.canonical_id`, `version_label`, `effective_date`, `published_date` 비교에 사용합니다.
- 기존 문서가 `index_status=indexed`이고 선택한 `embedding_profile_id`의 chunk embedding이 모두 `embedded`이며 `content_checksum`이 현재 chunk 본문과 맞으면 DB의 chunk와 embedding을 재사용합니다.
- metadata 기준 최신 문서가 이미 준비되어 있으면 전문 API, normalization, chunking, embedding API 호출을 모두 생략할 수 있습니다.
- 새 시행일 또는 새 version이면 기존 문서를 덮어쓰지 않고 별도 `legal_documents` version으로 저장합니다.
- 같은 canonical/version인데 전문 재조회 후 `normalized_checksum`이 다르면 자동 병합하거나 삭제하지 않고 `conflict_status=review_required`로 저장합니다.
- 외부 API 장애, rate limit, timeout이 발생하더라도 기존 indexed 문서가 있으면 임시로 cached/stale source로 사용할 수 있어야 하며, 이 상태는 metadata나 sync log에 남겨야 합니다.

## 2. Normalization

목표:

- HTML, XML, PDF, text를 검색 가능한 plain text로 변환합니다.
- 법률 문서 구조를 최대한 보존합니다.

입력:

- raw source text
- source metadata

출력:

- `legal_documents.normalized_text`
- 구조 metadata
- `legal_documents.normalized_checksum`
- `legal_documents.dedup_status`
- `legal_documents.conflict_status`

규칙:

- Korean text encoding을 UTF-8로 처리합니다.
- 조문 번호, 항, 호, 사건번호, 법원명, 선고일자를 가능한 보존합니다.
- parser가 실패해도 raw text는 보존합니다.
- 생성 직후 또는 indexing 전에는 `normalized_text`가 null일 수 있습니다.
- normalization 후 `normalized_checksum`을 계산하고, 같은 canonical/version의 기존 문서와 비교합니다.
- normalization 전에는 `raw_checksum`과 metadata만으로 중복 후보를 표시할 수 있지만, 최종 중복 판정은 가능한 한 `normalized_checksum` 기준으로 합니다.

중복/버전 판정 흐름:

```text
raw source 수집
  -> raw_checksum 계산
  -> normalization
  -> normalized_checksum 계산
  -> canonical_id + version_label/effective_date 조회
  -> normalized_checksum 동일: duplicate로 표시
  -> normalized_checksum 상이: conflict review로 표시
  -> version_label/effective_date 상이: 별도 version으로 보존
```

## 3. Legal-aware chunking

목표:

- citation 가능한 단위로 문서를 분리합니다.

chunk 기준:

- 법령: 조, 항, 호 단위 우선
- 판례: 사건명, 주문, 이유, 판단 섹션 우선
- 업로드 문서: heading 또는 paragraph 단위

출력:

- `legal_document_chunks`

필드:

- `document_id`
- `chunk_index`
- `heading`
- `content`
- `token_count`
- `metadata_json`

규칙:

- chunk 순서는 안정적이어야 합니다.
- 하나의 chunk는 너무 길지 않아야 합니다.
- citation에 필요한 source anchor를 metadata에 포함합니다.
- chunk row는 embedding 상태를 직접 갖지 않습니다. embedding 상태는 profile별 `legal_document_chunk_embeddings` row에서 관리합니다.

## 4. Embedding

목표:

- chunk text를 vector로 변환해 pgvector에 저장합니다.

입력:

- `legal_document_chunks.content`
- `AI_EMBEDDING_PROVIDER`
- `AI_EMBEDDING_MODEL`
- `AI_EMBEDDING_DIMENSIONS`
- `embedding_profiles`

출력:

- `embedding_profiles`
- `legal_document_chunk_embeddings.embedding`
- `legal_document_chunk_embeddings.embedding_status`
- `legal_document_chunk_embeddings.embedded_at`
- `legal_document_chunk_embeddings.content_checksum`

규칙:

- MVP는 OpenAI embedding provider를 사용합니다.
- 테스트는 mock embedding provider를 사용합니다.
- embedding 실패 시 chunk를 삭제하지 않고 `legal_document_chunk_embeddings.embedding_status=failed`로 표시합니다.
- embedding provider, model, dimension, distance metric 조합은 `embedding_profiles`로 저장합니다.
- 같은 chunk는 여러 profile로 임베딩될 수 있습니다.
- 검색은 반드시 하나의 `embedding_profile_id`를 선택한 뒤 같은 profile의 vector만 비교합니다.
- provider 응답 vector 길이는 `embedding_profiles.dimensions`와 일치해야 합니다.
- chunk 본문 checksum이 달라지면 기존 embedding은 `stale`로 간주하고 재임베딩합니다.
- model deprecation이 발생하면 기존 profile을 삭제하지 않고 `deprecated` 또는 `retired`로 표시한 뒤 새 profile로 재임베딩합니다.
- 공식 source preflight 결과 기존 문서와 chunk가 최신이면 같은 `embedding_profile_id`의 기존 embedding row를 재사용하고 embedding API를 다시 호출하지 않습니다.
- text normalization, chunking 설정, chunk 본문, 또는 embedding profile이 달라지면 기존 embedding을 재사용하지 않고 새 embedding row를 만들거나 기존 row를 `stale`로 전환합니다.

## 5. Retrieval

목표:

- 사용자 query와 관련 있는 chunk를 검색합니다.

입력:

- query
- search_mode: `focused_answer` 또는 `issue_spotting`
- top_k. 생략하면 search_mode별 기본값을 사용합니다.
- score_threshold
- max_chunks_per_document
- metadata filters

출력:

- ranked chunks
- score
- retrieval type

MVP 방식:

- query embedding 생성
- 선택된 `embedding_profile_id`의 chunk embedding만 대상으로 pgvector cosine similarity 기반 top-k 검색
- document type/date filter는 가능한 범위에서 적용
- `focused_answer`는 답변 생성에 바로 넣을 근거를 좁게 고르는 기본 모드입니다.
- `issue_spotting`은 한 사건에서 여러 조문, 구성요건, 쟁점을 넓게 탐지하기 위한 모드입니다. 이 모드에서는 기본 top-k를 크게 두고, 문서별 chunk 제한은 호출자가 명시한 경우에만 적용합니다.
- `score_threshold`가 지정되면 threshold 미만 결과를 제외합니다.
- `max_chunks_per_document`가 지정되면 한 문서가 검색 결과를 과도하게 차지하지 않게 제한합니다. 다만 형사 구성요건처럼 한 법령 문서 안의 여러 조문을 넓게 검토해야 하는 경우에는 생략할 수 있습니다.

후속 방식:

- PostgreSQL full-text search 추가
- vector + keyword hybrid retrieval
- reranking

## 6. Filtering and reranking

MVP:

- deterministic filter 위주
- document type, date, source type filter

후속:

- reranker model
- citation quality score
- 최신성 score
- source trust score

규칙:

- reranking 결과도 `rag_retrievals.rank`, `score`, `retrieval_type`으로 저장합니다.

## 7. Prompt assembly

입력:

- user facts
- user question
- retrieved chunks
- answer policy
- prompt version

규칙:

- retrieved chunks는 instruction이 아니라 evidence로 넣습니다.
- citation 없는 법률 주장을 금지합니다.
- 근거가 부족하면 추가 질문 또는 한계를 출력하게 합니다.
- 법률 자문이 아니라는 disclaimer를 포함합니다.

prompt version:

```text
RAG_PROMPT_VERSION=v1
```

## 8. Generation

MVP:

- `AI_AGENT_PROVIDER=openai`
- OpenAI provider adapter

출력:

- issue list 또는 answer draft
- citation list
- limits/uncertainty
- disclaimer
- provider/model metadata

규칙:

- provider raw response 전문은 저장하지 않습니다.
- provider 실패 시 `rag_runs.status=failed`로 저장합니다.

## 9. Citation validation

목표:

- 생성 결과의 법률 주장과 citation을 연결합니다.

MVP 기준:

- 응답 citation은 retrieved chunk ID만 사용할 수 있습니다.
- source URL과 title을 함께 반환합니다.
- 모델이 임의 chunk ID나 URL을 만들면 실패로 처리하거나 제거합니다.

후속 기준:

- claim 단위 citation 검증
- citation coverage 측정
- source excerpt matching

## 10. Persistence and audit

저장:

- `rag_runs`
- `rag_retrievals`
- `agent_steps`

`rag_runs` 필수 metadata:

- user ID
- run type
- status
- query
- agent provider/model. generation run에만 필요하며 retrieval-only run에서는 null 가능
- embedding profile ID
- embedding provider/model/dimensions
- prompt version
- answer 또는 failure reason

`rag_retrievals` 필수 metadata:

- run ID
- chunk ID
- vector 검색에 사용한 chunk embedding ID
- vector 검색에 사용한 embedding profile ID
- rank
- score
- retrieval type

`agent_steps` 필수 metadata:

- run ID
- step index
- step type
- MCP tool name. tool 호출이 아닌 step은 null 가능
- status
- redacted input/output metadata
- error code/message

## 11. MCP와 Agent 경계

RAG service는 검색과 citation mapping을 책임집니다. Agent는 이 기능을 직접 DB 접근으로 사용하지 않고 MCP tool을 통해 호출합니다.

MVP MCP tool:

- `search_legal_documents`: 내부 retrieval service 호출
- `search_law_open_api`: 실제 외부 법률 API 호출
- `verify_citations`: retrieved chunk와 외부 source metadata 기반 citation 검증

`search_law_open_api`의 `target`은 내부 `document_type`과 같은 `statute`, `case`, `interpretation`, `admin_appeal`을 사용합니다. 외부 API별 실제 query parameter 값은 adapter 내부에서 매핑합니다.

Agent 상태 흐름:

```text
initialize_run
  -> plan_issue_sources
  -> reasoning_loop
     -> propose_action
     -> validate_action
     -> execute_tool_or_model_step
     -> observe
     -> decide_continue_or_stop
  -> draft
  -> verify
  -> optional_repair_once
  -> persist
```

MVP에서는 이 흐름을 하나의 `OrchestratorAgent`가 수행합니다. MCP tool은 Agent가 아니며, Agent가 호출하는 제한된 service 경계입니다. LLM은 다음 action을 제안하지만 직접 tool을 실행하지 않습니다. Orchestrator는 action type, tool name, arguments, 권한, 반복 여부를 검증한 뒤 MCP tool 또는 provider adapter를 호출합니다.

허용 action type:

- `search_internal`
- `search_external_source`
- `sync_official_source`
- `draft_answer`
- `verify_citations`
- `respond_insufficient_evidence`
- `stop`

`sync_official_source`는 내부 RAG 근거가 부족하고 공식 source 후보가 있을 때만 실행합니다. 새 embedding이 만들어지지 않았거나 기존 indexed 문서가 재사용된 경우에도 retrieval 재실행 여부를 audit에 남깁니다.

초기 evidence 부족 판단은 단순하게 시작합니다. 내부 RAG 검색 결과 chunk가 없거나 citation 후보가 없으면 근거 부족으로 보고 공식 source 보강을 시도할 수 있습니다. 이후 평가 품질을 높일 때는 쟁점별 coverage, source type 다양성, 최신 법령 여부, 공식 source 여부, top-k 결과가 하나의 문서 또는 조문에 과도하게 몰리는지까지 함께 평가합니다.

후속 멀티에이전트 확장에서는 `SupervisorAgent`가 `IssueSpottingAgent`, `RetrievalAgent`, `LegalSourceAgent`, `DraftingAgent`, `CitationVerifierAgent`, `SafetyReviewAgent`의 호출 순서와 handoff를 결정합니다. 이 구조가 handoff, branching, retry, human-in-the-loop으로 복잡해지면 LangGraph로 이전할 수 있습니다.

제한:

- `max_iterations`와 `max_tool_calls`를 둡니다.
- `max_repeated_actions`, `max_external_sync_candidates`, timeout을 둡니다.
- 같은 action type과 arguments 조합이 반복되면 중단합니다.
- citation repair는 최대 1회만 수행합니다.
- allowlist에 없는 tool은 호출하지 않습니다.
- tool 결과는 prompt instruction이 아니라 evidence data로 취급합니다.
- tool input/output에는 secret, raw JWT, API key를 포함하지 않습니다.

저장하지 않음:

- provider API key
- auth cookie
- raw JWT
- 내부 prompt 전문

## MVP 완료 기준

- fixture 문서를 ingest할 수 있습니다.
- 문서가 chunk로 분리됩니다.
- chunk embedding이 `embedding_profiles`별로 저장됩니다.
- `/api/rag/search`가 `run_id`, `embedding_profile_id`, embedding metadata, 관련 chunk를 반환합니다.
- `/api/ai/dispute-issues`와 `/api/ai/answer-drafts`가 citation과 disclaimer를 포함합니다.
- AI run과 retrieval audit가 저장됩니다.

