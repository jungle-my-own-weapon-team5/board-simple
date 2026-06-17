# API 명세

## 문서 상태

이 문서는 두 범위를 함께 다룹니다.

- 현재 브랜치에 구현된 API
- FastAPI + pgvector 기반 명시적 RAG 구조를 위한 제안 API

`제안 AI/RAG API` 섹션의 endpoint는 설계 목표이며 현재 브랜치에는 아직 구현되어 있지 않습니다.

## 공통 규칙

### Base URL

- 로컬 backend: `http://localhost:8000`
- API prefix: `/api`
- health check: `/health`

### Content Type

JSON 요청은 다음 header를 사용합니다.

```http
Content-Type: application/json
```

### 인증

인증은 HttpOnly cookie를 사용합니다.

```text
access_token=<jwt>
```

프론트엔드는 credentials를 포함해 요청합니다. JavaScript에서 cookie 값을 직접 읽을 수 없습니다.

### Origin 요구사항

백엔드는 상태 변경 요청에서 `Origin` header가 `FRONTEND_ORIGIN`과 정확히 일치하지 않으면 요청을 거부합니다.

상태 변경 method:

- `POST`
- `PUT`
- `PATCH`
- `DELETE`

로컬 frontend origin:

```http
Origin: http://localhost:3000
```

### 오류 응답 형식

일반 오류는 FastAPI 표준 형식인 `detail` 필드를 사용합니다.

```json
{
  "detail": "Error message"
}
```

validation 오류는 FastAPI/Pydantic 기본 validation error 형식을 사용합니다.

## 구현된 API

## Health

### GET `/health`

backend 상태를 확인합니다.

#### Response `200`

```json
{
  "status": "ok"
}
```

## Auth

### POST `/api/auth/register`

사용자를 회원가입합니다.

허용된 `Origin` header가 필요합니다.

#### Request

```json
{
  "email": "user@example.com",
  "password": "password123",
  "nickname": "tester"
}
```

#### Validation

- `email`: 유효한 email
- `password`: 8자 이상 128자 이하
- `nickname`: 선택값, 2자 이상 32자 이하

`nickname`을 생략하면 `익명0000` 형식의 고유 닉네임을 생성합니다.

#### Response `201`

```json
{
  "id": 1,
  "email": "user@example.com",
  "nickname": "tester",
  "created_at": "2026-06-13T12:00:00Z"
}
```

#### Errors

- `403`: Origin이 없거나 허용되지 않음
- `409`: 이미 등록된 email
- `409`: 이미 등록된 nickname
- `422`: validation 오류

### POST `/api/auth/login`

사용자를 인증하고 HttpOnly 인증 cookie를 설정합니다.

허용된 `Origin` header가 필요합니다.

#### Request

```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

#### Response `200`

```json
{
  "id": 1,
  "email": "user@example.com",
  "nickname": "tester",
  "created_at": "2026-06-13T12:00:00Z"
}
```

#### Cookie

```text
Set-Cookie: access_token=<jwt>; HttpOnly; SameSite=Lax; Path=/
```

`Secure` 여부는 `AUTH_COOKIE_SECURE` 설정을 따릅니다.

#### Errors

- `401`: email 또는 password가 올바르지 않음
- `403`: Origin이 없거나 허용되지 않음
- `422`: validation 오류

### POST `/api/auth/logout`

인증 cookie를 삭제합니다.

허용된 `Origin` header가 필요합니다.

#### Response `204`

응답 본문이 없습니다.

### GET `/api/auth/me`

현재 인증된 사용자를 반환합니다.

`access_token` cookie가 필요합니다.

#### Response `200`

```json
{
  "id": 1,
  "email": "user@example.com",
  "nickname": "tester",
  "created_at": "2026-06-13T12:00:00Z"
}
```

#### Errors

- `401`: 인증 필요
- `401`: 유효하지 않은 인증 token
- `401`: 사용자를 찾을 수 없음

## Posts

### GET `/api/posts`

최신순으로 게시글 목록을 페이지 단위로 반환합니다.

#### Query Parameters

| Name | Type | Required | Default | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `page` | integer | no | `1` | `>= 1` | page number |
| `size` | integer | no | `10` | `1..50` | page size |
| `q` | string | no | `null` | | 제목 검색어 |

#### Response `200`

```json
{
  "items": [
    {
      "id": 1,
      "title": "Hello board",
      "author": {
        "id": 1,
        "nickname": "tester"
      },
      "tags": [
        {
          "id": 1,
          "name": "python"
        }
      ],
      "created_at": "2026-06-13T12:00:00Z",
      "updated_at": "2026-06-13T12:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "size": 10
}
```

### POST `/api/posts`

게시글을 생성합니다.

허용된 `Origin` header와 인증이 필요합니다.

#### Request

```json
{
  "title": "Hello board",
  "content": "Markdown body #Python"
}
```

#### Validation

- `title`: 1자 이상 200자 이하
- `content`: 1자 이상

태그는 `content`에서 `#태그명` 형식으로 추출합니다.

#### Response `201`

```json
{
  "id": 1,
  "title": "Hello board",
  "content": "Markdown body #Python",
  "author": {
    "id": 1,
    "nickname": "tester"
  },
  "tags": [
    {
      "id": 1,
      "name": "python"
    }
  ],
  "created_at": "2026-06-13T12:00:00Z",
  "updated_at": "2026-06-13T12:00:00Z"
}
```

#### Errors

- `401`: 인증 필요
- `403`: Origin이 없거나 허용되지 않음
- `422`: validation 오류

### GET `/api/posts/{post_id}`

게시글 상세를 반환합니다.

#### Response `200`

`POST /api/posts`와 같은 응답 형식을 사용합니다.

#### Errors

- `404`: 게시글을 찾을 수 없음

### PUT `/api/posts/{post_id}`

게시글을 수정합니다.

허용된 `Origin` header, 인증, 작성자 권한이 필요합니다.

#### Request

```json
{
  "title": "Updated title",
  "content": "Updated content #Django"
}
```

#### Response `200`

`POST /api/posts`와 같은 응답 형식을 사용합니다.

#### Errors

- `401`: 인증 필요
- `403`: Origin이 없거나 허용되지 않음
- `403`: 작성자만 수정 가능
- `404`: 게시글을 찾을 수 없음
- `422`: validation 오류

### DELETE `/api/posts/{post_id}`

게시글을 삭제합니다.

허용된 `Origin` header, 인증, 작성자 권한이 필요합니다.

#### Response `204`

응답 본문이 없습니다.

#### Errors

- `401`: 인증 필요
- `403`: Origin이 없거나 허용되지 않음
- `403`: 작성자만 삭제 가능
- `404`: 게시글을 찾을 수 없음

## Comments

### GET `/api/posts/{post_id}/comments`

특정 게시글의 댓글 목록을 페이지 단위로 반환합니다.

#### Query Parameters

| Name | Type | Required | Default | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `offset` | integer | no | `0` | `>= 0` | 건너뛸 댓글 수 |
| `limit` | integer | no | `5` | `1..50` | 반환할 댓글 수 |

#### Response `200`

```json
{
  "items": [
    {
      "id": 1,
      "post_id": 1,
      "content": "comment",
      "author": {
        "id": 1,
        "nickname": "tester"
      },
      "created_at": "2026-06-13T12:00:00Z",
      "updated_at": "2026-06-13T12:00:00Z"
    }
  ],
  "total": 1,
  "offset": 0,
  "limit": 5
}
```

#### Errors

- `404`: 게시글을 찾을 수 없음

### POST `/api/posts/{post_id}/comments`

댓글을 생성합니다.

허용된 `Origin` header와 인증이 필요합니다.

#### Request

```json
{
  "content": "comment"
}
```

#### Validation

- `content`: 1자 이상

#### Response `201`

```json
{
  "id": 1,
  "post_id": 1,
  "content": "comment",
  "author": {
    "id": 1,
    "nickname": "tester"
  },
  "created_at": "2026-06-13T12:00:00Z",
  "updated_at": "2026-06-13T12:00:00Z"
}
```

#### Errors

- `401`: 인증 필요
- `403`: Origin이 없거나 허용되지 않음
- `404`: 게시글을 찾을 수 없음
- `422`: validation 오류

### PUT `/api/comments/{comment_id}`

댓글을 수정합니다.

허용된 `Origin` header, 인증, 작성자 권한이 필요합니다.

#### Request

```json
{
  "content": "updated comment"
}
```

#### Response `200`

`POST /api/posts/{post_id}/comments`와 같은 응답 형식을 사용합니다.

#### Errors

- `401`: 인증 필요
- `403`: Origin이 없거나 허용되지 않음
- `403`: 작성자만 수정 가능
- `404`: 댓글을 찾을 수 없음
- `422`: validation 오류

### DELETE `/api/comments/{comment_id}`

댓글을 삭제합니다.

허용된 `Origin` header, 인증, 작성자 권한이 필요합니다.

#### Response `204`

응답 본문이 없습니다.

#### Errors

- `401`: 인증 필요
- `403`: Origin이 없거나 허용되지 않음
- `403`: 작성자만 삭제 가능
- `404`: 댓글을 찾을 수 없음

## Tags

### GET `/api/tags`

전체 태그를 이름 오름차순으로 반환합니다.

#### Response `200`

```json
[
  {
    "id": 1,
    "name": "python"
  }
]
```

## 제안 AI/RAG API

이 섹션의 endpoint는 명시적 RAG 서비스 구조를 위한 설계 목표입니다. 현재 브랜치에는 아직 구현되어 있지 않습니다.

### AI provider 규칙

MVP에서는 서버 설정의 `AI_RAG_ENABLED=true`, `AI_AGENT_PROVIDER=openai`, `AI_EMBEDDING_PROVIDER=openai`를 사용합니다. `AI_RAG_ENABLED=false`인 환경에서는 OpenAI key와 model 설정이 비어 있어도 됩니다.

클라이언트 요청은 provider를 직접 선택하지 않습니다. provider 선택은 서버 환경변수와 backend service 설정으로만 결정합니다. 이는 사용자가 임의로 더 비싼 provider나 허용되지 않은 provider를 호출하지 못하게 하기 위한 설계입니다.

후속 확장에서 Gemini와 Claude를 추가하더라도 API request/response shape는 유지합니다. provider별 차이는 backend provider adapter에서 처리합니다.

embedding은 단일 `vector(N)` 컬럼에 고정하지 않고 `embedding_profiles`로 선택합니다. 검색 API는 명시적으로 `embedding_profile_id`를 받을 수 있고, 생략하면 서버의 active default profile을 사용합니다. 서로 다른 embedding profile의 vector는 같은 검색 ranking에서 직접 비교하지 않습니다.

## Legal Documents

### POST `/api/legal-documents`

사용자가 제공한 계약서, PDF 추출 텍스트, 스캔본 OCR 결과, 메모 또는 입력 텍스트를 RAG 문서로 생성합니다.

초기 학습 버전은 JSON text 입력만 받아도 됩니다. 파일 업로드는 이후 단계에서 추가합니다.

인증이 필요합니다. role이 도입되면 admin-only로 제한해야 합니다.

이 endpoint는 사용자 제공 문서를 위한 경계입니다. 법령, 판례, 법령해석례, 행정심판례 같은 공식 법률 corpus 원문은 일반 사용자가 이 endpoint로 업로드하지 않고, backend가 국가법령정보 Open API 또는 허용된 공공 API에서 수집합니다.

이 endpoint는 backend가 `legal_sources` row를 함께 생성한 뒤 `legal_documents.source_id`에 연결합니다. JSON text 입력의 기본 source provider는 `upload`이고, fixture ingestion에서는 `fixture`를 사용합니다. 사용자 업로드의 기본 `document_type`은 `user_file` 또는 `memo`입니다.

frontend가 PDF text extraction을 수행할 수는 있지만 이는 미리보기와 사용자 확인을 위한 전처리입니다. backend는 전달받은 최종 text에 대해 normalization, checksum 계산, duplicate/conflict 판정, chunking을 다시 수행합니다.

backend는 요청의 `raw_text`에서 `raw_checksum`을 계산하고, normalization 이후 `normalized_checksum`을 계산합니다. 중복 판단은 checksum 단독이 아니라 `document_type`, `canonical_id`, `version_label` 또는 `effective_date`, `normalized_checksum` 조합으로 수행합니다. 같은 canonical/version인데 normalized checksum이 다르면 자동 삭제하지 않고 conflict 상태로 기록합니다.

#### Request

```json
{
  "document_type": "user_file",
  "title": "임대차계약서",
  "canonical_id": null,
  "source_url": null,
  "published_date": "2026-06-13",
  "effective_date": null,
  "raw_text": "사용자가 확인한 계약서 추출 텍스트..."
}
```

#### Response `201`

```json
{
  "id": 1,
  "source_id": 1,
  "document_type": "user_file",
  "title": "임대차계약서",
  "canonical_id": null,
  "version_label": null,
  "effective_date": null,
  "raw_checksum": "raw-checksum-value",
  "normalized_checksum": null,
  "dedup_status": "unique",
  "conflict_status": "none",
  "duplicate_of_document_id": null,
  "index_status": "pending",
  "chunk_count": 0,
  "created_at": "2026-06-13T12:00:00Z"
}
```

### POST `/api/legal-documents/{document_id}/index`

법률 문서를 정규화하고 chunk로 나누며 embedding을 생성해 색인합니다.

인증이 필요합니다. role이 도입되면 admin-only로 제한해야 합니다.

#### Request

```json
{
  "chunk_strategy": "legal_structure",
  "replace_existing": true
}
```

#### Response `202`

```json
{
  "document_id": 1,
  "status": "accepted"
}
```

초기 구현에서는 동기 처리 후 `200`을 반환할 수 있습니다. 큰 문서를 처리하게 되면 background job에 넣고 `202`를 반환합니다.

### GET `/api/legal-documents`

metadata와 keyword로 색인된 법률 문서를 검색합니다.

#### Query Parameters

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `q` | string | no | 제목 또는 keyword |
| `document_type` | string | no | `statute`, `case`, `interpretation`, `admin_appeal`, `user_file`, `memo` |
| `page` | integer | no | 기본값 `1` |
| `size` | integer | no | 기본값 `10`, 최대 `50` |

#### Response `200`

```json
{
  "items": [
    {
      "id": 1,
      "document_type": "case",
      "title": "Sample decision",
      "canonical_id": "2026-example-001",
      "version_label": null,
      "published_date": "2026-06-13",
      "effective_date": null,
      "dedup_status": "unique",
      "conflict_status": "none"
    }
  ],
  "total": 1,
  "page": 1,
  "size": 10
}
```

## RAG Search

### POST `/api/rag/search`

답변을 생성하지 않고 관련 법률 chunk만 검색합니다.

이 endpoint는 retrieval 품질을 디버깅하기 위해 필요합니다.

인증이 필요합니다.

#### Request

```json
{
  "query": "임대차 보증금 반환 분쟁에서 주요 쟁점은 무엇인가요?",
  "search_mode": "focused_answer",
  "top_k": null,
  "score_threshold": null,
  "max_chunks_per_document": 5,
  "embedding_profile_id": null,
  "filters": {
    "document_type": ["statute", "case"],
    "date_from": null,
    "date_to": null
  }
}
```

검색 옵션:

- `search_mode`: `focused_answer` 또는 `issue_spotting`. 생략하면 `focused_answer`입니다.
- `focused_answer`: 답변 생성에 바로 넣을 근거를 좁게 고르는 기본 모드입니다. `top_k` 생략 시 쟁점별 기본값은 `8`입니다.
- `issue_spotting`: 한 사건에서 여러 구성요건, 조문, 쟁점을 넓게 탐지해야 할 때 쓰는 모드입니다. `top_k` 생략 시 쟁점별 기본값은 `50`이고, 문서별 chunk 제한은 명시한 경우에만 적용합니다.
- `top_k`: 전체 사용자 입력 하나에 대한 총 결과 수가 아니라, Orchestrator LLM의 issue/source planning으로 생성된 각 쟁점별 RAG query에 적용되는 검색 예산입니다.
- `score_threshold`: `0` 이상 `1` 이하의 선택값입니다. 명시하면 threshold 미만 결과를 제외하고, `null` 또는 생략이면 score hard filter를 적용하지 않습니다. 서버 기본 관련도 점수로 최종 결과를 자동 삭제하지 않습니다.
- `max_chunks_per_document`: 선택값입니다. 특정 문서 하나가 검색 결과를 과도하게 차지하는 것을 제한합니다. `issue_spotting`에서는 누락 위험을 줄이기 위해 생략할 수 있습니다.

검색 실행 전 backend는 사용자 query에서 후보 쟁점과 공식 source 후보를 먼저 계획할 수 있습니다. 하나의 사건은 단일 법률 영역으로 제한하지 않고, `legal_domains[]`와 issue track을 복수로 가질 수 있습니다. 이후 track별 query로 retrieval을 수행하고, 같은 chunk가 여러 track에서 검색되면 중복을 병합합니다. 각 item의 `metadata`에는 가능하면 `planned_issue_key`, `planned_issue_title`, `planned_issue_query`, `planned_issue_queries`, `domain_tags`, `used_by_tracks`가 포함됩니다.

`planned_issue_queries`의 각 항목은 다음 필드를 포함할 수 있습니다.

```json
{
  "issue_key": "civil_damages",
  "issue_title": "불법행위 손해배상",
  "issue_query": "민법 불법행위 손해배상",
  "domain": "civil",
  "facts_slice": "손해 발생과 금전 청구 부분"
}
```

응답에서 같은 `chunk_id`는 한 번만 노출하며, 여러 track에 쓰이면 `used_by_tracks`로 연결합니다. UI는 이 정보를 사용해 전역 evidence index와 track별 근거 보기를 동시에 제공할 수 있습니다.

`issue_spotting` 목적의 클라이언트는 누락 위험을 줄이기 위해 `top_k`, `score_threshold`, `max_chunks_per_document`를 불필요하게 고정하지 않는 것을 권장합니다. 넓은 후보 수집 후 LLM evidence review가 쟁점별 필수 근거 coverage를 점검하고, 최종 citation은 `rag_retrievals`에 기록된 chunk 또는 검증된 공식 source metadata로 제한합니다.

#### Response `200`

```json
{
  "run_id": 1,
  "query": "임대차 보증금 반환 분쟁에서 주요 쟁점은 무엇인가요?",
  "embedding_profile_id": 1,
  "embedding_provider": "openai",
  "embedding_model_name": "configured-embedding-model",
  "embedding_dimensions": 1536,
  "items": [
    {
      "chunk_id": 10,
      "chunk_embedding_id": 25,
      "document_id": 1,
      "rank": 1,
      "score": 0.82,
      "title": "Sample decision",
      "source_url": "https://example.com/source",
      "heading": "판단",
      "content": "Relevant excerpt..."
    }
  ]
}
```

이 endpoint는 답변을 생성하지 않지만 검색 재현성을 위해 `rag_runs.run_type=search`와 `rag_retrievals`를 저장합니다. 이 경우 `rag_runs.agent_provider`와 `rag_runs.agent_model_name`은 null일 수 있습니다. vector 검색의 `rag_retrievals` row는 가능한 한 `chunk_embedding_id`와 `embedding_profile_id`를 함께 저장합니다.

## MCP JSON-RPC API

### POST `/api/mcp`

Agent가 allowlist된 MCP tool을 호출하기 위한 JSON-RPC endpoint입니다.

일반 사용자가 임의 tool을 직접 선택해 호출하는 공개 API로 사용하지 않습니다. MVP에서는 backend Agent orchestration이 서버 내부에서 호출하는 경계로 사용합니다.

#### `tools/list` Request

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "tools/list",
  "params": {}
}
```

#### `tools/list` Response `200`

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "tools": [
      {
        "name": "search_legal_documents",
        "description": "내부 pgvector 기반 법률 문서 검색",
        "input_schema": {
          "type": "object",
          "required": ["query"],
          "properties": {
            "query": { "type": "string" },
            "search_mode": { "type": "string", "enum": ["focused_answer", "issue_spotting"] },
            "top_k": { "type": "integer", "minimum": 1 },
            "score_threshold": { "type": "number", "minimum": 0, "maximum": 1 },
            "max_chunks_per_document": { "type": "integer", "minimum": 1 },
            "filters": { "type": "object" }
          }
        }
      },
      {
        "name": "search_law_open_api",
        "description": "국가법령정보 Open API 기반 외부 법률 자료 조회",
        "input_schema": {
          "type": "object",
          "required": ["query"],
          "properties": {
            "query": { "type": "string" },
            "target": { "type": "string", "enum": ["statute", "case", "interpretation", "admin_appeal"] },
            "limit": { "type": "integer", "minimum": 1, "maximum": 20 }
          }
        }
      },
      {
        "name": "verify_citations",
        "description": "생성 초안의 citation이 검색 결과에 근거하는지 검증",
        "input_schema": {
          "type": "object",
          "required": ["run_id", "citations"],
          "properties": {
            "run_id": { "type": "integer" },
            "citations": { "type": "array" }
          }
        }
      }
    ]
  }
}
```

#### `tools/call` Request

```json
{
  "jsonrpc": "2.0",
  "id": "req-2",
  "method": "tools/call",
  "params": {
    "name": "search_law_open_api",
    "arguments": {
      "query": "임대차 보증금 반환",
      "target": "statute",
      "limit": 5
    }
  }
}
```

`search_law_open_api.target`은 내부 `document_type`과 같은 값을 사용합니다. 국가법령정보 Open API의 실제 세부 구분값은 service adapter 내부에서 매핑합니다.

#### `tools/call` Response `200`

```json
{
  "jsonrpc": "2.0",
  "id": "req-2",
  "result": {
    "tool_name": "search_law_open_api",
    "items": [
      {
        "external_id": "law-001",
        "title": "주택임대차보호법",
        "source_url": "https://www.law.go.kr/...",
        "summary": "검색어와 관련된 법령 metadata 요약"
      }
    ]
  }
}
```

MCP 오류는 JSON-RPC error object로 반환합니다. 오류 메시지에는 API key, raw request header, 전체 분쟁 사실관계, 내부 prompt를 포함하지 않습니다.

예:

```json
{
  "jsonrpc": "2.0",
  "id": "req-3",
  "error": {
    "code": -32602,
    "message": "Invalid tool arguments",
    "data": {
      "error_code": "mcp_invalid_arguments"
    }
  }
}
```

## AI Agent API

MVP의 AI Agent API는 멀티에이전트가 아니라 단일 Orchestrator Agent를 기준으로 동작합니다. Orchestrator는 allowlist된 MCP tool을 순서대로 호출하고, 각 step을 `agent_steps`에 저장합니다. 멀티에이전트 확장 후에도 API request/response shape는 가능한 한 유지하고, Supervisor와 전문 Agent의 실행 details는 audit metadata로 분리합니다.

### POST `/api/ai/agent-runs`

쟁점 정리와 답변 초안 생성에서 공통으로 사용하는 Agent 실행 API입니다. UI는 단순화를 위해 `/api/ai/dispute-issues`와 `/api/ai/answer-drafts`를 먼저 호출해도 되지만, 내부 구현은 이 실행 모델을 기준으로 맞춥니다.

인증이 필요합니다.

#### Request

```json
{
  "task_type": "answer_draft",
  "facts": "임차인이 계약 종료 후 보증금을 돌려받지 못했습니다.",
  "question": "내용증명 초안 방향을 알려주세요.",
  "search_mode": "focused_answer",
  "top_k": 8,
  "score_threshold": null,
  "max_chunks_per_document": 5,
  "options": {
    "tone": "formal"
  }
}
```

Agent API의 retrieval 옵션은 `/api/rag/search`와 같은 의미를 가집니다. `top_k`는 전체 글 기준 결과 수가 아니라 쟁점별 검색 예산입니다. `score_threshold`는 명시한 경우에만 hard filter로 적용합니다. 복수 쟁점 탐지가 목적이면 `search_mode=issue_spotting`을 사용할 수 있으며, 이 경우 누락 방지를 위해 `top_k`, `score_threshold`, `max_chunks_per_document`를 기본적으로 비워둘 수 있습니다.

Agent는 사용자의 사건을 하나의 domain으로 고정하지 않고 복수 issue track으로 계획할 수 있습니다. 쟁점 정리와 답변 초안은 track별 검색 결과를 전역 evidence index로 병합한 뒤 cross-domain synthesis를 거쳐 생성합니다. 따라서 응답 citation은 track별 중복 citation이 아니라 병합된 evidence를 가리켜야 합니다.

#### Response `200`

```json
{
  "run_id": 2,
  "status": "completed",
  "task_type": "answer_draft",
  "agent_provider": "openai",
  "agent_model_name": "configured-agent-model",
  "tool_calls": [
    {
      "step_index": 2,
      "tool_name": "search_legal_documents",
      "status": "completed"
    },
    {
      "step_index": 4,
      "tool_name": "verify_citations",
      "status": "completed"
    }
  ],
  "result": {
    "draft": "초안 본문...",
    "citations": [
      {
        "chunk_id": 10,
        "title": "Sample decision",
        "source_url": "https://example.com/source"
      }
    ],
    "disclaimer": "이 결과는 법률정보 기반 초안 보조이며 법률 자문이 아닙니다."
  }
}
```

수행 중 저장되는 감사 정보:

- `rag_runs`: 사용자 요청, 상태, provider/model, prompt version
- `rag_retrievals`: 검색에 사용된 chunk와 순위
- `agent_steps`: plan, tool call, observe, draft, verify, error step metadata

### POST `/api/ai/dispute-issues`

사용자 사실관계와 검색된 법률 자료를 바탕으로 후보 쟁점을 정리합니다. 내부적으로 bounded Agent가 MCP tool을 호출할 수 있습니다.

인증이 필요합니다.

#### Request

```json
{
  "facts": "임차인이 계약 종료 후 보증금을 돌려받지 못했습니다.",
  "question": "어떤 쟁점을 정리해야 하나요?",
  "search_mode": "issue_spotting",
  "top_k": null
}
```

#### Response `200`

```json
{
  "run_id": 1,
  "agent_provider": "openai",
  "agent_model_name": "configured-agent-model",
  "issues": [
    {
      "title": "보증금 반환 청구 가능성",
      "summary": "계약 종료, 목적물 인도, 미지급 보증금 여부가 핵심입니다.",
      "missing_facts": [
        "계약 종료일",
        "목적물 인도 여부",
        "보증금 액수"
      ],
      "citations": [
        {
          "chunk_id": 10,
          "title": "Sample decision",
          "source_url": "https://example.com/source"
        }
      ]
    }
  ],
  "disclaimer": "이 결과는 법률정보 기반 초안 보조이며 법률 자문이 아닙니다."
}
```

### POST `/api/ai/answer-drafts`

사용자 사실관계와 검색된 법률 자료를 바탕으로 답변 초안을 생성합니다. 내부적으로 bounded Agent가 MCP tool 호출, 관찰, 초안 작성, citation 검증을 수행합니다.

인증이 필요합니다.

#### Request

```json
{
  "facts": "임차인이 계약 종료 후 보증금을 돌려받지 못했습니다.",
  "question": "내용증명 초안 방향을 알려주세요.",
  "tone": "formal",
  "search_mode": "focused_answer",
  "top_k": 8
}
```

#### Response `200`

```json
{
  "run_id": 2,
  "agent_provider": "openai",
  "agent_model_name": "configured-agent-model",
  "draft": "초안 본문...",
  "citations": [
    {
      "chunk_id": 10,
      "title": "Sample decision",
      "source_url": "https://example.com/source",
      "excerpt": "Relevant excerpt..."
    }
  ],
  "limits": [
    "제공된 사실관계가 제한적이므로 계약서와 반환 요청 내역 확인이 필요합니다."
  ],
  "disclaimer": "이 결과는 법률정보 기반 초안 보조이며 법률 자문이 아닙니다."
}
```

## AI/RAG 오류 규칙

AI/RAG endpoint는 다음 오류를 사용합니다.

- `400`: 지원하지 않는 document type, 잘못된 filter, 빈 facts, 잘못된 `search_mode`, `top_k`, `score_threshold`, `max_chunks_per_document`
- `401`: 인증 필요
- `403`: 권한 없음 또는 상태 변경 요청의 Origin 오류
- `404`: document 또는 run을 찾을 수 없음
- `409`: 동일 canonical/version 중복, canonical/version checksum 충돌, 또는 indexing 충돌
- `413`: request body 또는 업로드 content가 너무 큼
- `422`: validation 오류
- `429`: rate limit 초과
- `500`: 서버 provider 설정 오류
- `502`: 외부 법률 데이터 API, MCP tool, LLM provider 실패
- `503`: embedding, generation provider, MCP server 사용 불가

## AI/RAG 응답 요구사항

AI 생성 응답은 다음을 만족해야 합니다.

- 법률 주장에는 source citation을 포함합니다.
- 근거가 부족하면 불확실성을 명시합니다.
- 법률 자문이 아니라는 disclaimer를 포함합니다.
- audit을 위해 retrieved chunk IDs를 저장합니다.
- generation run에는 `agent_provider`, `agent_model_name`을 저장합니다.
- 모든 RAG run에는 `embedding_profile_id`, `embedding_provider`, `embedding_model_name`, `embedding_dimensions`를 저장합니다.
- Agent run에는 MCP tool call과 step metadata를 저장합니다.
- secret, raw JWT, 내부 prompt template을 노출하지 않습니다.

## API 설계 참고

- AI 생성 답변은 게시글과 분리해 저장합니다. 사용자가 나중에 초안을 게시글로 옮길 수는 있지만, AI run 자체는 별도 persistence model을 가져야 합니다.
- 답변 생성 API가 생긴 뒤에도 `POST /api/rag/search`는 유지합니다. retrieval 품질 디버깅은 RAG 시스템에서 필수입니다.
- 모델이 database, filesystem, shell을 직접 호출하게 하지 않습니다. Agent는 서버가 allowlist한 MCP tool만 호출하고, MCP tool은 backend service 경계를 통해 동작합니다.
- 외부 source sync를 일반 사용자에게 열기 전에 admin role 검사를 추가해야 합니다.
