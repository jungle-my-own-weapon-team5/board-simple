# DB 설계

## 문서 상태

- 대상: 현재 게시판 DB와 RAG 확장 DB 설계
- 구현 상태: 게시판 테이블은 구현됨, RAG 확장 테이블은 제안 상태
- 관련 문서: `docs/architecture.md`, `docs/api-spec.md`, `docs/requirements.md`, `docs/implementation-plan.md`, `docs/mcp-agent-design.md`

## 설계 원칙

- 게시판 도메인과 RAG 도메인을 테이블 수준에서 분리합니다.
- 법률 자료는 원천 source, 정규화 문서, 검색 chunk를 분리해 저장합니다.
- AI 생성 결과는 게시글과 분리해 `rag_runs`로 저장합니다.
- generation run에는 `agent_provider`, `agent_model_name`을 저장하고, 모든 RAG run에는 `embedding_provider`, `embedding_model_name`, `prompt_version`, retrieved chunk를 저장해 재현성과 감사 가능성을 확보합니다.
- MCP tool 호출과 Agent 상태 전이는 `agent_steps`로 저장합니다.
- secret, API key, raw JWT, auth cookie 값은 DB에 저장하지 않습니다.
- embedding dimension은 pgvector 컬럼의 `vector(N)`과 일치해야 하므로 모델 변경 시 migration 영향을 검토합니다.

## 현재 구현 테이블

### `users`

사용자 계정입니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `email` | varchar(255) | no | login email, unique |
| `password_hash` | varchar(255) | no | hashed password |
| `nickname` | varchar(32) | no | 표시 이름, unique |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

Index:

- `ix_users_id`
- `ix_users_email` unique
- `ix_users_nickname` unique

### `posts`

게시글입니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `author_id` | integer | no | `users.id` foreign key |
| `title` | varchar(200) | no | 게시글 제목 |
| `content` | text | no | Markdown content |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

Index:

- `ix_posts_id`
- `ix_posts_title`

Foreign key:

- `author_id -> users.id ON DELETE CASCADE`

### `comments`

게시글 댓글입니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `post_id` | integer | no | `posts.id` foreign key |
| `author_id` | integer | no | `users.id` foreign key |
| `content` | text | no | 댓글 본문 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

Index:

- `ix_comments_id`

Foreign keys:

- `post_id -> posts.id ON DELETE CASCADE`
- `author_id -> users.id ON DELETE CASCADE`

### `tags`

게시글 태그입니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `name` | varchar(50) | no | normalized tag name |

Index:

- `ix_tags_name` unique

### `post_tags`

게시글과 태그의 many-to-many 연결 테이블입니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `post_id` | integer | no | `posts.id` foreign key |
| `tag_id` | integer | no | `tags.id` foreign key |

Constraints:

- primary key: (`post_id`, `tag_id`)
- unique: `uq_post_tags_post_id_tag_id`

Foreign keys:

- `post_id -> posts.id ON DELETE CASCADE`
- `tag_id -> tags.id ON DELETE CASCADE`

## RAG 확장 테이블

## `legal_sources`

법률 자료의 원천 정보를 저장합니다. 같은 문서라도 출처, API, 업로드 방식은 별도로 추적합니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `provider` | varchar(50) | no | `law_open_api`, `scourt`, `upload`, `fixture` 등 |
| `source_type` | varchar(50) | no | `statute`, `case`, `interpretation`, `admin_appeal`, `user_file`, `memo` 등 |
| `external_id` | varchar(255) | yes | 외부 provider 식별자 |
| `source_url` | text | yes | 원문 또는 API 상세 URL |
| `fetched_at` | timestamptz | yes | 외부 source를 가져온 시각 |
| `metadata_json` | jsonb | no | provider-specific metadata |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- index: (`provider`, `source_type`)
- unique nullable policy: (`provider`, `external_id`)는 `external_id`가 있을 때만 unique
- index: `metadata_json` GIN은 필요할 때 추가

## `legal_documents`

정규화 가능한 법률 문서 단위입니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `source_id` | integer | no | `legal_sources.id` foreign key |
| `document_type` | varchar(50) | no | `statute`, `case`, `interpretation`, `admin_appeal`, `user_file`, `memo` 등 |
| `title` | varchar(500) | no | 문서 제목 |
| `canonical_id` | varchar(255) | yes | 법령 ID, 사건번호, 내부 문서 ID |
| `version_label` | varchar(100) | yes | 시행일, 선고일, 업로드 버전 등 |
| `published_date` | date | yes | 공포일, 선고일, 게시일 등 |
| `effective_date` | date | yes | 시행일 |
| `raw_text` | text | no | 원문 text |
| `normalized_text` | text | yes | 정규화된 text. 생성 직후 또는 indexing 전에는 null 가능 |
| `checksum` | varchar(128) | no | 중복 감지용 hash |
| `index_status` | varchar(30) | no | `pending`, `indexed`, `failed` |
| `indexed_at` | timestamptz | yes | 색인 완료 시각 |
| `index_error` | text | yes | 안전하게 정제된 색인 실패 사유 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- foreign key: `source_id -> legal_sources.id ON DELETE CASCADE`
- unique: `checksum`
- index: (`document_type`, `published_date`)
- index: `canonical_id`
- full-text index는 hybrid retrieval 도입 시 추가

`POST /api/legal-documents`처럼 사용자가 직접 텍스트를 입력하는 경우 backend는 `provider=upload` 또는 `provider=fixture`인 `legal_sources` row를 먼저 만들고, 생성된 `source_id`를 `legal_documents.source_id`에 연결합니다.

## `legal_document_chunks`

검색과 citation의 기본 단위입니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `document_id` | integer | no | `legal_documents.id` foreign key |
| `chunk_index` | integer | no | 문서 내 chunk 순서 |
| `heading` | varchar(500) | yes | 조문명, 제목, 판례 섹션 등 |
| `content` | text | no | chunk 본문 |
| `token_count` | integer | yes | 추정 token 수 |
| `embedding` | vector(N) | yes | pgvector embedding |
| `embedding_status` | varchar(30) | no | `pending`, `embedded`, `failed` |
| `embedded_at` | timestamptz | yes | embedding 완료 시각 |
| `embedding_error` | text | yes | 안전하게 정제된 embedding 실패 사유 |
| `metadata_json` | jsonb | no | 조문 번호, 법원, 사건번호 등 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- foreign key: `document_id -> legal_documents.id ON DELETE CASCADE`
- unique: (`document_id`, `chunk_index`)
- index: `document_id`
- index: `metadata_json` GIN은 metadata filter가 필요해질 때 추가
- vector index는 실제 데이터 적재 후 추가

pgvector index 후보:

```sql
CREATE INDEX ix_legal_document_chunks_embedding_hnsw
ON legal_document_chunks
USING hnsw (embedding vector_cosine_ops);
```

학습 초기에는 index 없이 정확한 검색을 먼저 확인하고, 데이터가 쌓인 후 HNSW 또는 IVFFlat을 선택합니다.

## `rag_runs`

사용자의 AI 요청과 생성 결과를 저장합니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `user_id` | integer | no | `users.id` foreign key |
| `run_type` | varchar(50) | no | `search`, `dispute_issues`, `answer_draft`, `agent_run` |
| `query` | text | no | 사용자 질문 또는 요청 |
| `facts` | text | yes | 사용자 사실관계, 민감정보 최소화 필요 |
| `status` | varchar(30) | no | `pending`, `completed`, `failed` |
| `answer` | text | yes | 생성 결과 |
| `disclaimer` | text | yes | 법률 자문 아님 고지 |
| `agent_provider` | varchar(50) | yes | 예: `openai`, `gemini`, `anthropic`, `mock`. retrieval-only run은 null 가능 |
| `agent_model_name` | varchar(100) | yes | generation model. retrieval-only run은 null 가능 |
| `embedding_provider` | varchar(50) | no | 예: `openai`, `mock` |
| `embedding_model_name` | varchar(100) | no | embedding model |
| `prompt_version` | varchar(50) | no | 예: `v1` |
| `error_code` | varchar(100) | yes | 실패 시 오류 code |
| `error_message` | text | yes | 실패 시 안전하게 정제된 오류 메시지 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- foreign key: `user_id -> users.id ON DELETE CASCADE`
- index: (`user_id`, `created_at`)
- index: (`status`, `created_at`)
- index: (`agent_provider`, `agent_model_name`)

주의:

- provider API key는 저장하지 않습니다.
- prompt 전문 저장은 신중하게 결정합니다. 초기에는 `prompt_version`과 retrieved chunk만 저장해도 충분합니다.
- `facts`는 민감정보가 될 수 있으므로 보존 정책을 별도로 정해야 합니다.
- MVP에서는 `facts` 전체 저장을 기본값으로 두지 않고, 필요한 경우 최소화 또는 마스킹 후 저장하는 정책을 우선 검토합니다.
- `run_type=search`는 LLM generation을 수행하지 않으므로 `agent_provider`, `agent_model_name`, `answer`, `disclaimer`가 null일 수 있습니다.

## `agent_steps`

Agent 실행 중 발생한 계획, MCP tool 호출, 관찰, 초안 작성, 검증, 실패 정보를 저장합니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `rag_run_id` | integer | no | `rag_runs.id` foreign key |
| `step_index` | integer | no | run 내 실행 순서 |
| `step_type` | varchar(50) | no | `plan`, `tool_call`, `tool_result`, `decide`, `draft`, `verify`, `error` |
| `tool_name` | varchar(100) | yes | MCP tool 이름. tool 호출이 아니면 null |
| `status` | varchar(30) | no | `pending`, `completed`, `failed`, `skipped` |
| `input_json` | jsonb | yes | secret과 raw 개인정보를 제거한 입력 metadata |
| `output_json` | jsonb | yes | secret과 raw 개인정보를 제거한 출력 metadata |
| `error_code` | varchar(100) | yes | 실패 시 오류 code |
| `error_message` | text | yes | 실패 시 안전하게 정제된 오류 메시지 |
| `started_at` | timestamptz | yes | step 시작 시각 |
| `finished_at` | timestamptz | yes | step 종료 시각 |
| `created_at` | timestamptz | no | 생성 시각 |

권장 constraints/index:

- foreign key: `rag_run_id -> rag_runs.id ON DELETE CASCADE`
- unique: (`rag_run_id`, `step_index`)
- index: (`rag_run_id`, `step_type`)
- index: (`tool_name`, `created_at`)

주의:

- `input_json`과 `output_json`에는 API key, Authorization header, raw JWT, 전체 provider request/response를 저장하지 않습니다.
- Agent loop 제한은 설정값과 실행 중 count로 관리하고, 사후 분석은 `agent_steps` 개수와 status로 확인합니다.

## `rag_retrievals`

각 AI run에서 어떤 chunk가 어떤 점수와 순위로 사용되었는지 저장합니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `rag_run_id` | integer | no | `rag_runs.id` foreign key |
| `chunk_id` | integer | no | `legal_document_chunks.id` foreign key |
| `rank` | integer | no | 검색 순위 |
| `score` | double precision | yes | similarity 또는 rerank score |
| `retrieval_type` | varchar(30) | no | `vector`, `keyword`, `hybrid`, `manual` |
| `created_at` | timestamptz | no | 생성 시각 |

권장 constraints/index:

- foreign key: `rag_run_id -> rag_runs.id ON DELETE CASCADE`
- foreign key: `chunk_id -> legal_document_chunks.id ON DELETE RESTRICT`
- unique: (`rag_run_id`, `chunk_id`)
- index: (`rag_run_id`, `rank`)
- index: `chunk_id`

## ERD 개요

```text
users
  ├─ posts
  ├─ comments
  └─ rag_runs
       ├─ agent_steps
       └─ rag_retrievals
            └─ legal_document_chunks
                 └─ legal_documents
                      └─ legal_sources

posts
  ├─ comments
  └─ post_tags
       └─ tags
```

## Migration 계획

권장 migration 순서:

1. `legal_sources` 생성
2. `legal_documents` 생성
3. `legal_document_chunks` 생성, embedding 컬럼은 확정 dimension으로 생성
4. `rag_runs` 생성
5. `agent_steps` 생성
6. `rag_retrievals` 생성
7. 기본 B-tree index 추가
8. fixture 데이터로 검색 품질 확인
9. 실제 데이터가 일정량 적재된 뒤 vector index 추가

## Embedding dimension 결정

`AI_EMBEDDING_DIMENSIONS`는 DB schema에 직접 영향을 줍니다.

예:

```text
AI_EMBEDDING_PROVIDER=openai
AI_EMBEDDING_MODEL=<selected-embedding-model>
AI_EMBEDDING_DIMENSIONS=<selected-dimension>
```

주의:

- `legal_document_chunks.embedding vector(N)`의 `N`은 migration 시 고정됩니다.
- embedding 모델을 바꾸면 기존 vector와 dimension이 달라질 수 있습니다.
- dimension 변경은 새 컬럼, 재색인, 또는 전체 re-embedding migration이 필요할 수 있습니다.
- `AI_RAG_ENABLED=false`인 동안에는 `.env.example`의 embedding 설정이 비어 있어도 됩니다. `AI_RAG_ENABLED=true`로 전환하기 전에 실제 `.env`에서 model과 dimension을 확정해야 합니다.

## Provider 저장 정책

MVP에서는 OpenAI를 사용합니다.

```text
AI_AGENT_PROVIDER=openai
AI_EMBEDDING_PROVIDER=openai
```

DB에는 provider 실행 결과를 추적하기 위해 다음을 저장합니다.

- generation run: `rag_runs.agent_provider`, `rag_runs.agent_model_name`
- 모든 RAG run: `rag_runs.embedding_provider`, `rag_runs.embedding_model_name`
- `rag_runs.prompt_version`
- MCP/Agent 실행: `agent_steps.step_type`, `agent_steps.tool_name`, `agent_steps.status`, redacted `input_json`, redacted `output_json`

DB에 저장하지 않는 것:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `LAW_OPEN_API_OC`
- 외부 API raw Authorization header
- provider raw request/response 전문
- auth cookie
- raw JWT

## 삭제 정책

초기 정책:

- 사용자가 삭제되면 해당 사용자의 `posts`, `comments`, `rag_runs`는 cascade 삭제합니다.
- 법률 source와 document는 전역 corpus로 취급하므로 사용자 삭제와 무관하게 유지합니다.
- `rag_retrievals`는 `rag_runs` 삭제 시 cascade 삭제합니다.
- `agent_steps`는 `rag_runs` 삭제 시 cascade 삭제합니다.
- `legal_document_chunks`는 audit 추적을 위해 기본적으로 restrict 또는 soft delete를 고려합니다.

추후 결정 필요:

- 사용자 업로드 문서를 shared corpus에 넣을지 user-private corpus로 분리할지
- 분쟁 사실관계와 AI run의 보존 기간
- 관리자 audit 접근 범위
