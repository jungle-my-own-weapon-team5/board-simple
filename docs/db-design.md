# DB 설계

## 문서 상태

- 대상: 현재 게시판 DB와 RAG 확장 DB 설계
- 구현 상태: 게시판 테이블은 구현됨, RAG 확장 테이블은 제안 상태
- 관련 문서: `docs/architecture.md`, `docs/api-spec.md`, `docs/requirements.md`, `docs/implementation-plan.md`, `docs/mcp-agent-design.md`

## 설계 원칙

- 게시판 도메인과 RAG 도메인을 테이블 수준에서 분리합니다.
- 법률 자료는 원천 source, 정규화 문서, 검색 chunk, embedding profile별 vector를 분리해 저장합니다.
- AI 생성 결과는 게시글과 분리해 `rag_runs`로 저장합니다.
- generation run에는 `agent_provider`, `agent_model_name`을 저장하고, 모든 RAG run에는 `embedding_profile_id`, `embedding_provider`, `embedding_model_name`, `embedding_dimensions`, `prompt_version`, retrieved chunk를 저장해 재현성과 감사 가능성을 확보합니다.
- MCP tool 호출과 Agent 상태 전이는 `agent_steps`로 저장합니다.
- secret, API key, raw JWT, auth cookie 값은 DB에 저장하지 않습니다.
- embedding model과 dimension은 `embedding_profiles`로 관리합니다. 같은 chunk는 여러 provider/model/dimension profile로 임베딩될 수 있으며, 서로 다른 profile의 vector를 같은 검색 공간에서 직접 비교하지 않습니다.
- 법률 문서는 단일 hash만으로 최종 진실을 판단하지 않습니다. 원문 hash, 정규화 hash, canonical/version metadata, 중복 상태, 충돌 상태를 함께 저장해 중복 제거와 버전 보존을 분리합니다.

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

국가법령정보 Open API metadata 저장 규칙:

- `external_id`에는 provider가 제공하는 안정적인 법령, 판례, 해석례, 행정심판례 식별자를 저장합니다.
- `metadata_json`에는 법령명, 법령 ID, 시행일, 공포일, 개정 식별자, 상세 조회 API path, source URL, metadata 응답 시각을 저장할 수 있습니다.
- `fetched_at`은 전문 또는 원문에 해당하는 raw payload를 실제로 가져온 시각을 의미합니다.
- 전문을 가져오기 전 metadata만 확인한 시각은 `metadata_json.last_metadata_checked_at` 또는 후속 sync log 테이블에 저장합니다.
- API key, 인증 토큰, 요청 secret은 `legal_sources`나 `metadata_json`에 저장하지 않습니다.

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
| `raw_checksum` | varchar(128) | no | 수집 원문 기준 hash |
| `normalized_checksum` | varchar(128) | yes | 정규화 text 기준 hash. normalization 전에는 null 가능 |
| `dedup_status` | varchar(30) | no | `unique`, `duplicate`, `superseded` 등 중복/대체 상태 |
| `conflict_status` | varchar(30) | no | `none`, `review_required`, `resolved` 등 canonical/version 충돌 상태 |
| `duplicate_of_document_id` | integer | yes | 중복으로 판단된 원본 `legal_documents.id` |
| `index_status` | varchar(30) | no | `pending`, `indexed`, `failed`, `replaced` |
| `indexed_at` | timestamptz | yes | 색인 완료 시각 |
| `index_error` | text | yes | 안전하게 정제된 색인 실패 사유 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- foreign key: `source_id -> legal_sources.id ON DELETE CASCADE`
- foreign key: `duplicate_of_document_id -> legal_documents.id ON DELETE SET NULL`
- index: (`document_type`, `published_date`)
- index: `canonical_id`
- index: (`document_type`, `canonical_id`, `effective_date`)
- index: (`document_type`, `canonical_id`, `version_label`)
- index: `raw_checksum`
- index: `normalized_checksum`
- index: (`dedup_status`, `conflict_status`)
- full-text index는 hybrid retrieval 도입 시 추가

`POST /api/legal-documents`처럼 사용자가 직접 텍스트를 입력하는 경우 backend는 `provider=upload` 또는 `provider=fixture`인 `legal_sources` row를 먼저 만들고, 생성된 `source_id`를 `legal_documents.source_id`에 연결합니다.

중복/버전/충돌 정책:

- `raw_checksum`은 수집 원문이 byte-level 또는 text-level로 같은지 확인하기 위한 값입니다.
- `normalized_checksum`은 normalization 후 실질 검색 본문이 같은지 판단하기 위한 값입니다.
- `normalized_checksum`이 null인 indexing 전 문서는 `raw_checksum`과 canonical/version metadata만으로 임시 중복 후보를 판단합니다.
- `checksum` 단독 unique constraint는 사용하지 않습니다. 공백, 줄바꿈, wrapper 차이로 같은 법률 내용의 hash가 달라질 수 있고, 반대로 같은 법령의 다른 시행 버전을 단순 중복으로 오해할 수 있기 때문입니다.
- 중복 판단은 `document_type`, `canonical_id`, `version_label` 또는 `effective_date`, `normalized_checksum`을 함께 사용합니다.
- 같은 `document_type`, `canonical_id`, `version_label` 또는 `effective_date`인데 `normalized_checksum`이 다르면 자동 삭제하지 않고 `conflict_status=review_required`로 저장합니다.
- `effective_date` 또는 `version_label`이 다르면 같은 canonical document의 다른 버전으로 보존합니다.
- 완전 중복으로 판단한 문서는 `dedup_status=duplicate`, `duplicate_of_document_id`로 원본 문서를 가리키고, 검색 색인 대상에서는 제외할 수 있습니다.
- 최신 법령만 최종 진실로 간주해 과거 버전을 삭제하지 않습니다. 분쟁 발생 시점에 따라 과거 시행 버전이 근거가 될 수 있습니다.
- 재색인으로 같은 canonical/version의 기존 문서를 대체할 때 과거 retrieval 이력이 없으면 기존 문서를 삭제할 수 있습니다. 이력이 있으면 감사 추적을 위해 row와 chunk를 보존하되 `index_status=replaced`로 전환해 검색 후보와 중복/충돌 판정에서 제외합니다.

공식 source 최신성/preflight 정책:

- 국가법령정보 Open API 같은 공식 provider는 전문 API를 호출하기 전에 metadata API로 최신성 정보를 먼저 확인합니다.
- preflight metadata의 `document_type`, `canonical_id`, `version_label`, `effective_date`, `published_date`가 기존 `legal_documents` row와 일치하고 `index_status=indexed`이면 전문 API 호출을 생략할 수 있습니다.
- 전문 API를 생략하는 경우 기존 `legal_document_chunks`와 선택된 `embedding_profile_id`의 `legal_document_chunk_embeddings`를 재사용합니다.
- 단, chunking schema version이 현재 backend의 `chunking_schema_version`과 다르면 전문 API를 다시 조회해 chunking과 embedding을 재수행합니다. 이때 기존 검색 이력이 없는 문서는 삭제하고, 이력이 있는 문서는 `index_status=replaced`로 전환합니다.
- 새 `effective_date` 또는 새 `version_label`이 발견되면 기존 문서를 수정하지 않고 새 `legal_documents` row로 저장합니다.
- 같은 canonical/version인데 전문 재조회 후 `normalized_checksum`이 달라지면 자동 갱신하지 않고 `conflict_status=review_required`로 저장합니다.
- provider metadata만으로 동일 version 여부를 확정하기 어렵다면 전문을 가져와 normalization과 checksum 비교를 수행합니다.

## `legal_document_chunks`

검색과 citation의 기본 단위입니다. chunk row는 원문 조각과 citation metadata만 책임지고, embedding vector와 embedding 처리 상태는 `legal_document_chunk_embeddings`에 profile별로 분리해 저장합니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `document_id` | integer | no | `legal_documents.id` foreign key |
| `chunk_index` | integer | no | 문서 내 chunk 순서 |
| `heading` | varchar(500) | yes | 조문명, 제목, 판례 섹션 등 |
| `content` | text | no | chunk 본문 |
| `token_count` | integer | yes | 추정 token 수 |
| `metadata_json` | jsonb | no | 조문 번호, 조문 제목, chunking schema version, 법원, 사건번호 등 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- foreign key: `document_id -> legal_documents.id ON DELETE CASCADE`
- unique: (`document_id`, `chunk_index`)
- index: `document_id`
- index: `metadata_json` GIN은 metadata filter가 필요해질 때 추가

## `embedding_profiles`

임베딩 provider, model, dimension, 거리 계산 방식을 하나의 검색 공간 단위로 정의합니다. 하나의 chunk는 여러 profile로 임베딩될 수 있지만, 서로 다른 profile의 vector를 같은 검색에서 직접 비교하지 않습니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `provider` | varchar(50) | no | 예: `openai`, `mock`, `anthropic`, `voyage` 등 |
| `model_name` | varchar(150) | no | provider의 embedding model 이름 |
| `dimensions` | integer | no | embedding vector 차원 |
| `distance_metric` | varchar(30) | no | `cosine`, `l2`, `inner_product` 등 |
| `vector_type` | varchar(30) | no | `vector`, `halfvec` 등 저장/index 전략 |
| `status` | varchar(30) | no | `active`, `deprecated`, `retired` |
| `is_default` | boolean | no | 기본 검색 profile 여부 |
| `metadata_json` | jsonb | no | provider별 옵션, deprecation 사유, 운영 메모 등 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- unique: (`provider`, `model_name`, `dimensions`, `distance_metric`)
- index: (`status`, `is_default`)
- check: `dimensions > 0`

주의:

- `provider` 값은 DB schema를 OpenAI에 고정하지 않기 위해 문자열로 둡니다. 다만 실제 호출 가능 여부는 provider adapter가 `ProviderCapabilityError` 등으로 검증합니다.
- Anthropic/Claude가 embedding 기능을 직접 제공하지 않는 환경에서는 `provider=anthropic` profile을 활성화하지 않습니다. 구조는 향후 provider 지원 또는 호환 embedding provider 도입을 막지 않기 위한 것입니다.
- model deprecation이 발생하면 기존 profile을 즉시 삭제하지 않고 `deprecated` 또는 `retired`로 표시한 뒤 새 profile로 재임베딩합니다.

## `legal_document_chunk_embeddings`

chunk별 embedding 결과를 profile 단위로 저장합니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `chunk_id` | integer | no | `legal_document_chunks.id` foreign key |
| `embedding_profile_id` | integer | no | `embedding_profiles.id` foreign key |
| `embedding` | vector | yes | pgvector embedding. profile의 `dimensions`로 길이를 검증 |
| `embedding_status` | varchar(30) | no | `pending`, `embedded`, `failed`, `stale` |
| `embedded_at` | timestamptz | yes | embedding 완료 시각 |
| `embedding_error` | text | yes | 안전하게 정제된 embedding 실패 사유 |
| `content_checksum` | varchar(128) | no | embedding 당시 chunk content hash |
| `metadata_json` | jsonb | no | provider response ID 등 secret이 아닌 metadata |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- foreign key: `chunk_id -> legal_document_chunks.id ON DELETE CASCADE`
- foreign key: `embedding_profile_id -> embedding_profiles.id ON DELETE RESTRICT`
- unique: (`chunk_id`, `embedding_profile_id`)
- index: (`embedding_profile_id`, `embedding_status`)
- index: `chunk_id`
- index: `content_checksum`

규칙:

- embedding 성공 시 `embedding_status=embedded`, 실패 시 `failed`로 저장하고 chunk와 document는 삭제하지 않습니다.
- chunk 본문이 바뀌어 `content_checksum`이 달라지면 기존 embedding은 `stale`로 간주하고 같은 profile로 재임베딩할 수 있어야 합니다.
- `embedding` 컬럼은 profile별 dimension을 저장할 수 있도록 고정 `vector(N)` 대신 일반 `vector`를 사용합니다. application/service 계층은 반환 vector 길이가 `embedding_profiles.dimensions`와 같은지 검증해야 합니다.
- 검색은 반드시 하나의 `embedding_profile_id`를 선택한 뒤 같은 profile의 embedding끼리만 비교합니다.
- 공식 source preflight 결과 문서와 chunk가 최신이면 같은 `embedding_profile_id`의 기존 `embedded` row를 재사용합니다.
- chunk `content_checksum`, embedding profile, normalization 결과, chunking 설정이 달라진 경우 기존 embedding row를 최신 결과로 간주하지 않습니다.

pgvector index 후보:

```sql
CREATE INDEX ix_chunk_embeddings_profile_1_hnsw
ON legal_document_chunk_embeddings
USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
WHERE embedding_profile_id = 1 AND embedding_status = 'embedded';
```

학습 초기에는 index 없이 정확한 검색을 먼저 확인하고, 데이터가 쌓인 후 profile별 partial/expression index로 HNSW 또는 IVFFlat을 선택합니다. pgvector index는 같은 dimension끼리 만들어야 하므로, 여러 dimension을 하나의 index로 섞지 않습니다.

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
| `embedding_profile_id` | integer | yes | 검색 query embedding에 사용한 `embedding_profiles.id` |
| `embedding_provider` | varchar(50) | no | 예: `openai`, `mock` |
| `embedding_model_name` | varchar(100) | no | embedding model |
| `embedding_dimensions` | integer | yes | 검색 query embedding dimension snapshot |
| `prompt_version` | varchar(50) | no | 예: `v1` |
| `error_code` | varchar(100) | yes | 실패 시 오류 code |
| `error_message` | text | yes | 실패 시 안전하게 정제된 오류 메시지 |
| `created_at` | timestamptz | no | 생성 시각 |
| `updated_at` | timestamptz | no | 수정 시각 |

권장 constraints/index:

- foreign key: `user_id -> users.id ON DELETE CASCADE`
- foreign key: `embedding_profile_id -> embedding_profiles.id ON DELETE SET NULL`
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
MVP에서는 단일 Orchestrator Agent의 step을 저장합니다. 멀티에이전트 확장 후에는 Supervisor와 전문 Agent 실행, handoff, 검증 step도 같은 audit 흐름으로 추적합니다.

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
- MVP의 `agent_steps` schema는 단일 Orchestrator Agent를 기준으로 충분합니다.
- 멀티에이전트 workflow로 확장할 때는 후속 migration으로 `agent_name`, `parent_step_id`, `handoff_from_step_id`, `handoff_reason`, `confidence`, `requires_human_review`를 추가할 수 있습니다.
- `parent_step_id`와 `handoff_from_step_id`는 Supervisor가 어떤 전문 Agent 실행을 시작했는지, 어떤 결과가 다음 Agent로 넘겨졌는지 추적하기 위한 후보입니다.
- `confidence`와 `requires_human_review`는 전문 Agent의 불확실성 또는 사용자/관리자 검토 필요성을 audit에 남기기 위한 후보입니다.

## `rag_retrievals`

각 AI run에서 어떤 chunk가 어떤 점수와 순위로 사용되었는지 저장합니다.

| Column | Type | Nullable | 설명 |
| --- | --- | --- | --- |
| `id` | integer | no | primary key |
| `rag_run_id` | integer | no | `rag_runs.id` foreign key |
| `chunk_id` | integer | no | `legal_document_chunks.id` foreign key |
| `chunk_embedding_id` | integer | yes | vector 검색에 사용한 `legal_document_chunk_embeddings.id` |
| `embedding_profile_id` | integer | yes | vector 검색에 사용한 `embedding_profiles.id` |
| `rank` | integer | no | 검색 순위 |
| `score` | double precision | yes | similarity 또는 rerank score |
| `retrieval_type` | varchar(30) | no | `vector`, `keyword`, `hybrid`, `manual` |
| `created_at` | timestamptz | no | 생성 시각 |

권장 constraints/index:

- foreign key: `rag_run_id -> rag_runs.id ON DELETE CASCADE`
- foreign key: `chunk_id -> legal_document_chunks.id ON DELETE RESTRICT`
- foreign key: `chunk_embedding_id -> legal_document_chunk_embeddings.id ON DELETE SET NULL`
- foreign key: `embedding_profile_id -> embedding_profiles.id ON DELETE SET NULL`
- unique: (`rag_run_id`, `chunk_id`)
- index: (`rag_run_id`, `rank`)
- index: `chunk_id`
- index: (`embedding_profile_id`, `retrieval_type`)

주의:

- `retrieval_type=vector`인 row는 가능한 한 `chunk_embedding_id`와 `embedding_profile_id`를 함께 저장합니다.
- `retrieval_type=keyword`, `hybrid`, `manual`에서는 vector embedding이 직접 사용되지 않을 수 있으므로 `chunk_embedding_id`가 null일 수 있습니다.

## ERD 개요

```text
users
  ├─ posts
  ├─ comments
  └─ rag_runs
       ├─ agent_steps
       ├─ rag_retrievals
       │    ├─ legal_document_chunk_embeddings
       │    │    └─ embedding_profiles
       │    └─ legal_document_chunks
       └─ embedding_profiles
            (embedding_profile_id)

legal_document_chunks
  ├─ legal_document_chunk_embeddings
  │    └─ embedding_profiles
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
3. `legal_documents.duplicate_of_document_id` self-reference foreign key 추가
4. `legal_document_chunks` 생성
5. `embedding_profiles` 생성
6. `legal_document_chunk_embeddings` 생성
7. `rag_runs` 생성
8. `agent_steps` 생성
9. `rag_retrievals` 생성
10. 기본 B-tree index 추가
11. fixture 데이터로 중복, 버전, 충돌 판정과 검색 품질 확인
12. 실제 데이터가 일정량 적재된 뒤 profile별 vector index 추가

## Embedding profile과 dimension 결정

임베딩 dimension은 더 이상 `legal_document_chunks.embedding vector(N)`처럼 단일 컬럼에 고정하지 않습니다. 대신 `embedding_profiles`가 검색 공간을 정의하고, `legal_document_chunk_embeddings`가 profile별 vector를 저장합니다.

예:

```text
AI_EMBEDDING_PROVIDER=openai
AI_EMBEDDING_MODEL=<selected-embedding-model>
AI_EMBEDDING_DIMENSIONS=<selected-dimension>
```

주의:

- `AI_EMBEDDING_PROVIDER`, `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_DIMENSIONS`는 기본 profile 생성 또는 기본 검색 profile 선택에 사용합니다.
- `embedding_profiles.dimensions`는 provider 응답 vector 길이 검증의 기준입니다.
- embedding model이나 dimension을 바꾸면 기존 profile을 덮어쓰지 않고 새 profile을 생성합니다.
- 기존 embedding model이 deprecated되면 기존 row는 보존하고 profile `status`를 `deprecated` 또는 `retired`로 바꾼 뒤 새 profile로 re-embedding합니다.
- pgvector의 일반 `vector` 컬럼은 여러 dimension 저장을 허용하지만, HNSW/IVFFlat index는 같은 dimension끼리 profile별 partial/expression index로 만들어야 합니다.
- dimension이 큰 model은 pgvector index 전략에 영향을 줄 수 있습니다. 필요하면 `vector_type=halfvec` 같은 별도 저장/index 전략을 profile metadata로 기록합니다.
- `AI_RAG_ENABLED=false`인 동안에는 `.env.example`의 embedding 설정이 비어 있어도 됩니다. `AI_RAG_ENABLED=true`로 전환하기 전에 실제 `.env`에서 model과 dimension을 확정해야 합니다.

## Provider 저장 정책

MVP에서는 OpenAI를 사용합니다.

```text
AI_AGENT_PROVIDER=openai
AI_EMBEDDING_PROVIDER=openai
```

DB에는 provider 실행 결과를 추적하기 위해 다음을 저장합니다.

- generation run: `rag_runs.agent_provider`, `rag_runs.agent_model_name`
- 모든 RAG run: `rag_runs.embedding_profile_id`, `rag_runs.embedding_provider`, `rag_runs.embedding_model_name`, `rag_runs.embedding_dimensions`
- `rag_runs.prompt_version`
- chunk embedding: `legal_document_chunk_embeddings.embedding_profile_id`, `embedding_status`, `content_checksum`
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
- `legal_document_chunk_embeddings`는 chunk 삭제 시 cascade 삭제합니다.
- `embedding_profiles`는 검색 재현성과 재임베딩 이력을 위해 기본적으로 삭제하지 않고 `status`로 사용 중지합니다.

추후 결정 필요:

- 사용자 업로드 문서를 shared corpus에 넣을지 user-private corpus로 분리할지
- 분쟁 사실관계와 AI run의 보존 기간
- 관리자 audit 접근 범위
- 멀티에이전트 확장 시 `agent_steps`를 확장할지, 별도 `agent_handoffs` 테이블을 만들지
