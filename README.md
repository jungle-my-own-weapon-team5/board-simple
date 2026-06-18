# 역사 덕담

조선시대 인물, 사건, 제도, 문화에 대해 글을 쓰고 토론하는 역사 커뮤니티 게시판입니다.

이 브랜치의 핵심은 일반 게시판 CRUD 위에 **글쓰기 화면 옆 에디터 AI Agent**를 붙인 것입니다. 사용자는 게시글을 작성하다가 Agent 패널에 자연어로 요청할 수 있고, Agent는 안전성 검사, 요청 의도 분류, 내부 RAG 검색, 외부 근거 검색, 응답 생성을 거쳐 제목/본문/태그/토론 질문을 에디터에 바로 반영할 수 있게 돌려줍니다.

현재 브랜치: `codex/hyeyeon-feature-issues`

## 핵심 기능

### 게시판 기본 기능

- 이메일/비밀번호 회원가입, 로그인, 로그아웃
- HttpOnly 쿠키 기반 JWT 인증
- 닉네임 unique 검증과 `익명0000` 형식 자동 닉네임 생성
- 내 정보 페이지, 닉네임 변경, 내 글/내 댓글 목록
- 게시글 CRUD
- Markdown 작성, 미리보기, 렌더링
- 글 유형, 카테고리, 태그, 썸네일, 조회수, 댓글 수 표시
- 댓글 작성, 수정, 삭제
- 댓글 `View more` 방식 페이지네이션
- 게시글 제목 검색과 페이지네이션
- 태그 목록 조회
- Redis 기반 캐시 사용 가능

### AI 기능

- 게시글 작성 화면의 에디터 AI Agent
- 전역 AI 챗봇
- AI 글쓰기 보조
- AI 썸네일 후보 생성
- 오늘의 토론거리 생성 및 관리자 편집
- RAG 검색 API
- RAG 품질 개선 Agent 검색 API
- 외부 자료 검색 API
- JSON-RPC 2.0 MCP 서버
- 관리자 전용 AI Playground

### Safety Layer

서버 측 Safety Layer가 게시글 작성/수정, 썸네일 생성, AI 챗봇, 에디터 Agent 요청을 먼저 검사합니다.

차단 대상 예시:

- 역사 게시판 맥락에서 벗어난 요청
- 자살/자해, 폭력/무기, 성적 요청, 혐오
- 개인정보 추적
- 불법행위 조력
- 고위험 의학/법률/금융 조언
- 역사적 설명이 아니라 실행 방법을 요구하는 위험 요청

역사적/교육적 맥락의 민감 주제는 허용하지만, 실제 실행을 돕는 방향이면 RAG, MCP, LLM 호출 전에 안내 응답을 반환합니다.

## 기술 스택

### Frontend

- Next.js App Router
- React
- TypeScript
- Tailwind CSS
- shadcn/ui 스타일의 로컬 UI 컴포넌트
- lucide-react
- zustand
- react-markdown, rehype-sanitize

### Backend

- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL
- Redis
- LangGraph
- OpenAI API

### AI / Search

- OpenAI LLM 모델: `OPENAI_LLM_MODEL`
- OpenAI embedding 모델: `OPENAI_EMBEDDING_MODEL`
- OpenAI image 모델: `OPENAI_IMAGE_MODEL`
- 내부 RAG seed: `backend/rag_seed/**/*.md`
- RAG 저장 테이블: `rag_documents`, `rag_chunks`
- 외부 검색: Naver discovery, Sillok search 중심
- MCP endpoint: `POST /api/mcp`

### DB와 pgvector 상태

마이그레이션에는 PostgreSQL `vector` extension, `rag_chunks.embedding vector(1536)` 컬럼, HNSW index가 포함되어 있습니다.

다만 현재 런타임의 RAG 검색 코드는 SQL의 pgvector 연산을 직접 쓰기보다, `rag_chunks.embedding_json`에 저장된 embedding을 읽어서 Python에서 cosine similarity를 계산합니다. 따라서 README에서는 “pgvector 준비됨”과 “현재 검색 구현은 embedding_json 기반”을 구분해서 이해해야 합니다.

## 전체 아키텍처

```mermaid
flowchart LR
  U[사용자] --> FE[Next.js Frontend]
  FE --> PF[PostForm<br/>MarkdownEditor + Agent 패널]
  PF --> API[FastAPI<br/>POST /api/ai/editor-agent/run]
  API --> SAFE[Safety 검사]
  SAFE --> LG[LangGraph Editor Agent]
  LG --> RAG[RAG Runtime<br/>search_rag]
  RAG --> DB[(PostgreSQL<br/>rag_documents / rag_chunks)]
  LG --> EXT[External Evidence Bundle<br/>search_external]
  EXT --> MCP[MCP Tools<br/>Sillok / Naver / Web / Image]
  LG --> RESP[EditorAgentResponse]
  RESP --> PF
```

큰 흐름은 다음과 같습니다.

1. 사용자가 글쓰기 화면에서 Agent에게 자연어 요청을 보냅니다.
2. 프론트엔드는 현재 제목, 본문, 글 유형, 카테고리, 최근 대화 기록을 함께 백엔드로 보냅니다.
3. 백엔드는 Safety 검사를 먼저 수행합니다.
4. 검사를 통과하면 LangGraph 기반 Editor Agent가 실행됩니다.
5. Agent는 내부 RAG 자료와 외부 검색 후보를 활용해 답변 또는 본문 초안을 만듭니다.
6. 결과는 `EditorAgentResponse`로 프론트에 반환됩니다.
7. 사용자는 본문 적용, 아래에 추가, 제목 적용, 태그 추가 버튼으로 결과를 에디터에 반영합니다.

## 에디터 AI Agent

파일:

- Backend: `backend/app/services/editor_agent.py`
- API: `backend/app/api/ai.py`
- Frontend API: `frontend/src/api/ai.ts`
- Frontend UI: `frontend/src/components/PostForm.tsx`

### 실제 API

```http
POST /api/ai/editor-agent/run
```

요청에 포함되는 주요 정보:

- `title`: 현재 게시글 제목
- `content`: 현재 게시글 본문
- `post_type`: 글 유형
- `category`: 카테고리
- `message`: 사용자가 Agent에게 보낸 메시지
- `history`: 최근 Agent 대화 기록

응답에 포함되는 주요 정보:

- `agent_message`: Agent가 사용자에게 보여줄 답변
- `suggested_content`: 본문 초안 또는 수정안
- `suggested_title`: 추천 제목
- `tags`: 추천 태그
- `questions`: 토론 질문
- `citations`: 내부 RAG 근거
- `external_resources`: 외부 자료 후보
- `tool_logs`: 외부 도구 실행 로그
- `agent_steps`: Agent 단계별 실행 로그
- `weak_evidence`: 근거가 약한지 여부

### LangGraph 노드

현재 실제 LangGraph 노드는 네 개입니다.

```mermaid
flowchart LR
  I[intent] --> R[retrieve]
  R --> E[external_search]
  E --> P[respond]
```

Safety 검사는 LangGraph 노드가 아닙니다. 그래프 실행 전에 먼저 수행됩니다.

정확한 실행 흐름:

```text
Safety 검사
→ intent
→ retrieve
→ external_search
→ respond
```

#### 1. Safety 검사

`run_editor_agent()` 진입 직후 두 번 검사합니다.

1. 사용자 메시지 자체 검사
2. 사용자 메시지 + 제목 + 본문을 합친 전체 맥락 검사

문제가 있으면 LangGraph를 실행하지 않고 안전 응답을 반환합니다.

#### 2. intent 노드

사용자 요청을 세 가지 액션 중 하나로 분류합니다.

- `answer`: 질문 답변
- `fill_content`: 본문 생성
- `revise_content`: 본문 수정

또한 RAG 검색에 사용할 `rag_query`를 만듭니다.

예시:

```text
"장녹수에 대해 알려줘"
→ answer

"양녕대군 고양이 사건으로 게시글 초안 써줘"
→ fill_content

"이 문단을 더 자연스럽게 고쳐줘"
→ revise_content
```

#### 3. retrieve 노드

내부 RAG를 검색합니다.

```python
search_rag(db, settings, query, 3)
```

검색 결과는 그대로 쓰지 않고 다음 기준으로 필터링합니다.

- 질문 핵심어와 맞는가
- citation relevance가 기준 이상인가
- 인물/사건명이 불일치하지 않는가

채택 가능한 citation이 없으면 `weak_evidence=True`가 됩니다.

#### 4. external_search 노드

외부 근거 후보를 찾습니다.

```python
search_external(db, settings, keyword)
```

현재 흐름은 “RAG가 실패하면 외부 검색”만은 아닙니다. `answer`, `fill_content` 요청은 내부 RAG 확인 뒤 외부 검색 후보도 함께 확인하는 쪽에 가깝습니다.

외부 검색 keyword는 인물명만 남기지 않고 사건/일화 키워드를 보존하도록 개선했습니다.

예시:

```text
이전:
"양녕대군의 고양이 사건 알려줘"
→ "양녕대군"

현재:
"양녕대군의 고양이 사건 알려줘"
→ "양녕대군 고양이 사건"
```

이 단계에서 `external.search`, `evidence.judge` 실행 로그가 남습니다. 단, `evidence.judge`는 별도 LangGraph 노드가 아니라 `external_search` 단계 안에서 남기는 로그입니다.

#### 5. respond 노드

최종 응답을 생성합니다.

사용하는 정보:

- 사용자 원래 요청
- 현재 게시글 제목과 본문
- intent 결과
- RAG citation
- 외부 자료 후보
- weak_evidence 여부

`OPENAI_API_KEY`가 있으면 LLM을 사용하고, 없거나 실패하면 local fallback 응답을 만듭니다.

## 사용자 시나리오

### 시나리오 1. 인물 질문

사용자:

```text
장녹수에 대해 알려줘
```

흐름:

1. `intent`: `answer`로 분류
2. `retrieve`: 내부 RAG에서 장녹수 관련 자료 검색
3. `external_search`: 외부 검색 후보 확인
4. `respond`: 인물 설명과 근거 후보 반환

### 시나리오 2. 본문 생성

사용자:

```text
양녕대군 고양이 사건으로 게시글 초안 써줘
```

흐름:

1. `intent`: `fill_content`로 분류
2. `retrieve`: 내부 RAG에서 관련 근거 검색
3. `external_search`: `양녕대군 고양이 사건` 키워드로 외부 근거 후보 검색
4. `respond`: `suggested_content` 생성
5. Frontend: 사용자가 `본문에 적용` 또는 `아래에 추가` 버튼으로 반영

### 시나리오 3. 본문 수정

사용자:

```text
이 문단을 더 자연스럽게 고쳐줘
```

흐름:

1. `intent`: `revise_content`로 분류
2. 현재 제목/본문 맥락 확인
3. 필요하면 내부 RAG와 외부 검색 결과 참고
4. `respond`: 수정된 문장 또는 본문 제안 반환

### 시나리오 4. 근거가 약한 질문

상황:

- 내부 RAG에 직접 근거가 없음
- 외부 검색도 질문 핵심 사건을 직접 뒷받침하지 못함

기대 동작:

- `weak_evidence=True`
- 단정하지 않고 “현재 확보한 근거로는 확인이 어렵다”는 방향으로 응답
- 외부 자료 후보가 인물 설명뿐이면 사건 자체를 입증한 것으로 다루지 않아야 함

이 시나리오는 RAG/MCP를 붙이는 것만으로 충분하지 않고, “찾은 자료가 질문의 핵심을 실제로 뒷받침하는가”를 계속 개선해야 한다는 회고 포인트입니다.

## RAG 구조

파일:

- Runtime: `backend/app/services/ai_runtime.py`
- Models: `backend/app/models/ai.py`
- Seed: `backend/rag_seed/**/*.md`
- Embedding script: `backend/scripts/embed_rag_chunks.py`

### 데이터 모델

`rag_documents`

- 문서 단위 메타데이터
- 주요 컬럼:
  - `title`
  - `period`
  - `source_url`
  - `source_type`
  - `corpus`
  - `metadata_json`

`rag_chunks`

- 문서를 검색 가능한 조각으로 나눈 단위
- 주요 컬럼:
  - `document_id`
  - `chunk_index`
  - `content`
  - `embedding_json`
  - PostgreSQL 환경에서는 migration으로 `embedding vector(1536)` 컬럼도 추가됨

### Seed 동기화

RAG 검색이 실행되면 `_ensure_seed_documents(db)`가 `backend/rag_seed/**/*.md` 파일을 DB에 동기화합니다.

seed Markdown은 frontmatter와 본문으로 구성됩니다.

런타임 정규화 과정에서는 다음 처리가 포함됩니다.

- HTML entity unescape
- 특수 공백 정리
- 불필요한 번호 패턴 제거
- 한자 alias 추가
- `## 원문` 이후 원문 섹션 제거
- 공백/개행 정리
- metadata 저장

### 검색 방식

`OPENAI_API_KEY`가 있으면:

1. 사용자 query를 embedding으로 변환
2. DB의 `embedding_json`과 cosine similarity 계산
3. title/metadata keyword 기반 relevance boost 적용
4. relevance threshold 이상만 citation으로 채택

`OPENAI_API_KEY`가 없으면:

1. query에서 keyword 추출
2. chunk content와 document title에 keyword가 포함되는지 확인
3. keyword match score 기반으로 citation 반환

즉 쉽게 말하면:

```text
OpenAI 키가 있으면 의미 기반 검색
없으면 단어 매칭 검색
```

### Corpus 우선순위

RAG 검색 API는 `corpus` 값을 받습니다.

지원 값:

- `auto`
- `encykorea`
- `legacy`
- `sinpyeon_hanguksa`
- `all`

`auto` 동작:

- 일반 개괄 질문: `encykorea` overview 자료를 먼저 검색
- `실록`, `원문`, `사료`, `기록`, `국역` 같은 원문 지향 질문: 기존 실록 seed인 `legacy`를 먼저 검색

응답의 `searched_corpora`에서 실제 검색 대상 corpus를 확인할 수 있습니다.

## 외부 검색과 MCP

파일:

- Runtime: `backend/app/services/ai_runtime.py`
- MCP server: `backend/app/services/mcp_server.py`
- API endpoint: `backend/app/api/mcp.py`

### 외부 검색 흐름

```mermaid
flowchart TD
  K[external keyword] --> N[Naver discovery]
  N --> S[Sillok search 후보 생성]
  S --> R[trusted domain ranking]
  R --> O[ExternalResource 목록]
```

`search_external()`은 외부 근거 후보를 묶어서 반환합니다.

현재 중심 흐름:

1. Naver discovery로 후보 검색
2. 검색 결과를 바탕으로 실록 검색 query 생성
3. 조선왕조실록 검색 결과 파싱
4. trusted domain ranking
5. `ExternalSearchResponse` 반환
6. `tool_logs` 저장

현재 코드에서 `web_enabled`는 false로 두고 있어, raw resource가 없으면 `web:disabled` 상태가 붙을 수 있습니다.

### MCP endpoint

```http
POST /api/mcp
```

Protocol:

- JSON-RPC 2.0

Supported methods:

- `initialize`
- `tools/list`
- `tools/call`

Tools:

- `history.search_sillok`
- `history.naver_search`
- `history.web_search`
- `image.generate_thumbnail`

MCP 호출 예시:

```bash
curl -X POST http://localhost:8000/api/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"history.search_sillok","arguments":{"keyword":"세종"}}}'
```

## 전역 AI 챗봇

파일:

- `backend/app/services/chat_agent.py`
- `frontend/src/components/AiChatWidget.tsx`

전역 챗봇은 로그인 사용자용 Agent입니다. 현재 페이지 맥락과 사용자 메시지를 바탕으로 게시판 기능을 도와줍니다.

LangGraph 흐름:

```text
prepare_context → run_retrieval_agent
```

지원되는 capability 예시:

- `user.my_posts`: 내 글 찾기
- `user.my_comments`: 내 댓글 찾기
- `post.search`: 게시글 검색

그 외 질문은 RAG/외부 자료 Agent 흐름을 통해 답변합니다.

## 오늘의 토론거리

파일:

- `backend/app/services/discussion_topics.py`
- `backend/app/models/ai.py`
- `frontend/src/screens/AdminDiscussionTopicsPage.tsx`

기능:

- 날짜별 토론거리 3개 카드 생성
- 최근 게시글, 댓글 수, 조회수, 작성 시점, RAG citation 활용
- OpenAI API 키가 있으면 카드 문구와 글쓰기 초안을 LLM으로 생성
- DB에 날짜별로 캐시
- 관리자는 토론거리 재생성, 고정, 숨김, 문구/초안 수정 가능

관련 API:

- `GET /api/ai/topics`
- `GET /api/admin/discussion-topics`
- `POST /api/admin/discussion-topics/refresh`
- `PATCH /api/admin/discussion-topics/{topic_id}`

## AI 썸네일

파일:

- `backend/app/services/mcp_server.py`
- `frontend/src/screens/AdminThumbnailPage.tsx`
- `frontend/src/components/PostForm.tsx`

글 작성 화면에서 저장 전에 썸네일 후보 3개를 생성할 수 있습니다.

동작:

1. 제목/본문/카테고리/태그를 기반으로 이미지 프롬프트 생성
2. `OPENAI_API_KEY`가 있으면 OpenAI Images API 호출
3. 생성 이미지는 `backend/app/static/generated/` 아래 저장
4. 사용자가 후보 중 하나를 선택하면 게시글의 `thumbnail_url`로 저장

제목이나 본문이 너무 짧으면 생성하지 않고 보강 안내를 반환합니다.

관리자는 `/admin/thumbnail`에서 게시글 저장 없이 썸네일 생성을 테스트할 수 있습니다.

## 프로젝트 구조

```text
.
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI router
│   │   ├── core/                # config, DB, security
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── services/            # Agent, RAG, MCP, safety
│   │   └── static/generated/    # generated thumbnails
│   ├── alembic/                 # DB migrations
│   ├── rag_seed/                # RAG Markdown seed
│   ├── scripts/                 # seed/embedding/import scripts
│   ├── tests/                   # pytest
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/                 # API clients
│   │   ├── app/                 # Next.js routes
│   │   ├── components/          # reusable UI
│   │   ├── screens/             # page screens
│   │   └── stores/              # zustand stores
│   ├── Dockerfile
│   └── package.json
├── docs/
├── outputs/
│   └── presentation-materials/  # drawio 발표 자료
├── docker-compose.yml
├── .env.example
└── README.md
```

## 환경변수

루트 `.env` 파일을 사용합니다.

```bash
cp .env.example .env
```

주요 변수:

```env
DATABASE_URL=postgresql+psycopg://board:board@localhost:5432/board
DOCKER_DATABASE_URL=postgresql+psycopg://board:board@db:5432/board
JWT_SECRET_KEY=change-me
FRONTEND_ORIGIN=http://localhost:3000
AUTH_COOKIE_SECURE=false

OPENAI_API_KEY=
OPENAI_LLM_MODEL=gpt-5.4-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_IMAGE_MODEL=gpt-image-1
OPENAI_THUMBNAIL_SIZE=1536x1024

REDIS_URL=redis://localhost:6379/0
RAG_CACHE_TTL_SECONDS=600
THUMBNAIL_CACHE_TTL_SECONDS=3600

ADMIN_EMAIL=admin@example.com
ADMIN_NICKNAME=관리자

NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
BRAVE_SEARCH_API_KEY=

NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

주의:

- 로컬에서 backend를 직접 실행하면 `DATABASE_URL` host는 `localhost`가 맞습니다.
- Docker Compose 안의 backend는 DB host로 `db`를 써야 하므로 `DOCKER_DATABASE_URL`을 사용합니다.
- `.env.example`의 기본 `DATABASE_URL`은 Docker 기준으로 되어 있을 수 있으니, 로컬 실행 시 반드시 확인하세요.
- OpenAI API 키가 없으면 대부분의 AI 기능은 local fallback 또는 demo 응답으로 동작합니다.
- Naver API 키가 없으면 Naver discovery는 `not_configured` 상태가 될 수 있습니다.

## 로컬 개발 실행

권장 방식:

- PostgreSQL과 Redis는 Docker로 실행
- FastAPI는 로컬 reload 모드
- Next.js는 로컬 dev 모드

### 1. DB와 Redis 실행

```bash
docker compose up -d db redis
```

### 2. Backend 실행

Windows PowerShell:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

macOS/Linux:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### 3. Frontend 실행

```bash
cd frontend
npm install
npm run dev
```

개발 서버:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

상태 확인:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/api/posts?page=1&size=10"
```

## Docker Compose 실행

전체 서비스를 Docker로 실행합니다.

```bash
docker compose up --build
```

서비스:

- `db`: `pgvector/pgvector:pg16`
- `redis`: `redis:7-alpine`
- `migrate`: `alembic upgrade head`
- `backend`: FastAPI, `http://localhost:8000`
- `frontend`: Next.js, `http://localhost:3000`

종료:

```bash
docker compose down
```

DB/Redis volume까지 삭제:

```bash
docker compose down -v
```

## 테스트

Backend 테스트:

```bash
cd backend
pytest
```

특정 테스트 예시:

```bash
cd backend
pytest tests/test_auth_posts_comments.py
pytest tests/test_auth_posts_comments.py -k "external_keyword or naver_discovery_query"
pytest tests/test_rag_normalization.py
```

최근 확인한 관련 테스트:

```text
tests/test_auth_posts_comments.py
26 passed
```

## 더미 데이터

```bash
cd backend
python scripts/seed_dummy_data.py
```

더미 유저 비밀번호:

```text
password123
```

관리자 테스트 계정:

```text
admin@example.com / password123
```

## RAG seed 수집과 embedding

### 조선왕조실록 seed 수집

```bash
cd backend
python scripts/fetch_sillok_seed.py --limit-per-record 50 --clean
```

공식 조선왕조실록 자료열람 페이지에서 왕대/편찬본별 기사 일부를 가져와 `backend/rag_seed/sillok/` 아래 Markdown 파일로 저장합니다.

### 한국민족문화대백과사전 overview seed 수집

```bash
cd backend
python scripts/fetch_encykorea_seed.py --delay 3 --continue-on-error
```

원본 HTML과 파싱 JSON은 `backend/raw_seed/encykorea/`에 보관하고, 임베딩용 Markdown은 `backend/rag_seed/overview/encykorea/`에 생성합니다.

### 신편 한국사 seed 수집

```bash
cd backend
python scripts/fetch_sinpyeon_history_seed.py
```

신편 한국사 overview 자료를 수집합니다. 자동 RAG 우선순위에는 기본 포함되지 않을 수 있으므로, 명시 corpus 검색이나 별도 embedding 상태를 확인해야 합니다.

### RAG chunk 동기화와 embedding 생성

```bash
cd backend
python scripts/embed_rag_chunks.py --sync-only
python scripts/embed_rag_chunks.py --corpus encykorea --batch-size 100
python scripts/embed_rag_chunks.py --batch-size 100
```

설명:

- `--sync-only`: seed Markdown을 DB의 `rag_documents`, `rag_chunks`까지 동기화하고 embedding API는 호출하지 않음
- `--corpus encykorea`: 특정 corpus만 embedding
- embedding 생성에는 `OPENAI_API_KEY` 필요
- 이미 `embedding_json`이 있는 chunk는 건너뜀

## API Overview

### Auth / User

- `POST /api/auth/register`: 회원가입
- `POST /api/auth/login`: 로그인, HttpOnly JWT 쿠키 설정
- `POST /api/auth/logout`: 로그아웃, 쿠키 삭제
- `GET /api/auth/me`: 현재 사용자 조회
- `PATCH /api/users/me`: 닉네임 변경
- `GET /api/users/me/posts?page=&size=`: 내 글 목록
- `GET /api/users/me/comments?page=&size=`: 내 댓글 목록

### Posts / Comments / Tags

- `GET /api/posts?page=&size=&q=`: 게시글 목록, 제목 검색
- `POST /api/posts`: 게시글 생성
- `GET /api/posts/{post_id}`: 게시글 상세
- `PUT /api/posts/{post_id}`: 게시글 수정
- `DELETE /api/posts/{post_id}`: 게시글 삭제
- `GET /api/posts/{post_id}/comments?offset=&limit=`: 댓글 목록
- `POST /api/posts/{post_id}/comments`: 댓글 작성
- `PUT /api/comments/{comment_id}`: 댓글 수정
- `DELETE /api/comments/{comment_id}`: 댓글 삭제
- `GET /api/tags`: 태그 목록

### AI

- `GET /api/ai/topics`: 오늘의 토론거리 3개 카드
- `POST /api/ai/writing-assist`: 제목/태그/카테고리/토론 질문 추천
- `POST /api/ai/editor-agent/run`: 에디터 안에서 질문 답변, 본문 생성, 본문 수정 처리
- `POST /api/ai/rag/search`: RAG citation 검색
- `POST /api/ai/rag/agent-search`: RAG 품질 개선 Agent 검색
- `POST /api/ai/external/search`: 외부 자료 검색
- `POST /api/ai/agent/run`: Agent 실행 단계와 tool log 데모
- `POST /api/ai/agent/chat`: 로그인 사용자용 전역 챗봇 Agent
- `POST /api/ai/comments/summarize`: 댓글 요약

### Admin

- `GET /api/admin/discussion-topics`: 관리자 전용 오늘의 토론거리 목록/설정 조회
- `POST /api/admin/discussion-topics/refresh`: 관리자 전용 오늘의 토론거리 재생성
- `PATCH /api/admin/discussion-topics/{topic_id}`: 관리자 전용 토론거리 고정/숨김/문구/초안 수정
- `POST /api/admin/thumbnail/preview`: 관리자 전용 썸네일 생성 테스트

### MCP

- `POST /api/mcp`: JSON-RPC 2.0 MCP endpoint

## 발표 자료

프로젝트 기반 아키텍처 draw.io 파일:

```text
outputs/presentation-materials/current-project-architecture.drawio
```

구성:

- `1. 현재 코드 기준 아키텍처`
- `2. Editor Agent 실제 실행 흐름`

발표에서 가장 안전한 한 문장:

```text
Agent가 중심이고, RAG는 내부 근거 검색, MCP/외부 검색은 근거 보강 도구입니다.
```

말하면 안 되는 표현:

- `plan node`가 별도로 있다
- `evidence node`가 별도로 있다
- `quality gate node`가 별도로 있다
- 서버가 실시간 stream progress event를 보낸다

현재 코드 기준으로는 위 표현들이 정확하지 않습니다.

## 구현상 주의점과 현재 한계

### 1. RAG 품질은 seed 전처리에 크게 의존

자료를 많이 넣는 것만으로 검색 품질이 좋아지지 않습니다.

현재 전처리에서 중요한 부분:

- 한자 원문 섹션 제거
- Markdown seed 정규화
- metadata 저장
- title/keyword relevance boost
- overview 자료와 원문 자료의 corpus 분리

### 2. 외부 검색은 query rewriting 품질에 영향받음

예를 들어 `양녕대군 고양이 사건`을 물었는데 검색어가 `양녕대군`으로 줄어들면 인물 설명만 가져오게 됩니다.

이를 줄이기 위해 현재는 인물명만 남기지 않고 사건/일화 키워드를 보존합니다.

### 3. 외부 자료가 질문 핵심을 증명하는지 따로 봐야 함

외부 검색에서 `양녕대군` 인물 설명을 찾았다고 해서 `고양이 사건` 자체가 입증되는 것은 아닙니다.

좋은 응답은 다음처럼 조심해야 합니다.

```text
현재 확보한 근거로는 해당 사건 자체를 직접 확인하기 어렵습니다.
```

### 4. pgvector 준비와 현재 검색 구현은 구분해야 함

DB에는 vector extension과 vector column/index가 준비되어 있지만, 현재 runtime 검색은 `embedding_json`을 읽어 Python에서 cosine similarity를 계산합니다.

### 5. Frontend 진행률은 서버 stream이 아님

`PostForm.tsx`에는 Agent 대기 중 진행 표시 UI가 있습니다.

표시 단계:

- 요청 의도 분석
- RAG 근거 검색
- 외부 자료 확인
- 답변 구성

다만 이것은 서버가 단계별 event를 streaming하는 구조가 아니라, 프론트에서 대기 중 보여주는 UI입니다.

## 브랜치 작업 메모

최근 이 브랜치에서 반영한 내용:

- 현재 코드 기준 draw.io 아키텍처 작성
- Notion 발표 대본 구조 정리
- `editor_agent._focused_external_keyword()` 개선
- 인물명 + 사건/일화 키워드 보존
- 관련 테스트 추가

검증:

```bash
cd backend
python -m pytest tests/test_auth_posts_comments.py
```

