# Board Simple

Next.js + FastAPI + PostgreSQL(pgvector)로 구성한 기본 게시판입니다.

## Branch Strategy

- `main`: 메인 브랜치입니다. `README.md`를 포함한 최소 파일/폴더만 존재합니다.
- `dev`: 프로젝트에서 사용할 기반 프로젝트까지만 구현한 브랜치입니다.
- `project/{nickname}`: 각자 사용할 브랜치입니다. 기반 프로젝트에 기반하여 AI를 활용한 추가 기능들을 붙인 프로젝트입니다.

## Features

- 이메일/비밀번호 회원가입, 로그인, 로그아웃
- HttpOnly 쿠키 기반 JWT 인증
- 닉네임 unique 검증과 `익명0000` 형식 자동 닉네임 생성
- 내 정보 페이지, 닉네임 변경, 내 글/내 댓글 목록
- 게시글 CRUD, Markdown 작성/미리보기/표시
- 게시 전 AI 썸네일 후보 3개 생성, 사용자 선택 후 저장
- 서버 측 Safety Layer로 역사 주제와 무관하거나 유해·민감한 게시글/AI 요청 차단
- 댓글 작성과 `View more` 방식 페이지네이션
- `#태그명` 형식 태그 추출
- 게시글 제목 검색과 페이지네이션
- `역사 덕담` 기획 기반 글 유형/카테고리, 조회수, 댓글 수 표시
- 오늘의 토론거리, AI 글쓰기 보조, RAG/MCP/Agent 데모 API
- 로그인 사용자용 전역 AI 챗봇, 에디터 범용 Agent, 관리자 전용 AI Playground
- `OPENAI_API_KEY` 설정 시 OpenAI Responses API와 Embeddings API 기반 AI/RAG 실행

## Stack

- FE: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui, zustand
- BE: FastAPI, Pydantic, SQLAlchemy, Alembic, LangChain, LangGraph
- DB: PostgreSQL with pgvector
- Container: Docker, Docker Compose

## Project Structure

```text
.
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/app/
│   ├── src/components/
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
├── .env.example
└── README.md
```

## 환경변수

로컬 개발과 Docker Compose 실행 모두 루트 `.env` 파일을 사용합니다.

```bash
cp .env.example .env
```

필요한 환경변수는 `.env.example`에 정리되어 있습니다.

로컬 개발에서는 PostgreSQL만 Docker로 실행하고, backend/frontend는 내 컴퓨터에서 직접 실행합니다. 이 경우 DB host는 `localhost`를 사용합니다.

```env
DATABASE_URL=postgresql+psycopg://board:board@localhost:5432/board
```

AI 기능은 키가 없으면 로컬 데모 응답으로 동작하고, 키가 있으면 OpenAI API를 호출합니다.

```env
OPENAI_API_KEY=
OPENAI_LLM_MODEL=gpt-5.4-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_IMAGE_MODEL=gpt-image-1
OPENAI_THUMBNAIL_SIZE=1536x1024
ADMIN_EMAIL=admin@example.com
ADMIN_NICKNAME=관리자
NATIONAL_LIBRARY_API_KEY=
```

전체 Docker 실행에서는 backend가 Docker Compose 네트워크 안에서 실행됩니다. 이 경우 DB host는 `db`를 사용합니다. 로컬 실행용 `DATABASE_URL`과 충돌하지 않도록 Docker Compose는 `DOCKER_DATABASE_URL`을 우선 사용하고, 없으면 아래 값을 기본으로 씁니다.

```env
DOCKER_DATABASE_URL=postgresql+psycopg://board:board@db:5432/board
```

## 개발용 실행 방법

개발할 때는 아래 방식을 권장합니다.

- PostgreSQL(pgvector)은 Docker에서 실행합니다.
- FastAPI는 로컬에서 reload 모드로 실행합니다.
- Next.js는 로컬에서 hot reload 모드로 실행합니다.

DB를 실행합니다.

```bash
docker compose up -d db
```

backend를 실행합니다.

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Windows PowerShell에서는 아래 명령을 사용합니다.

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

다른 터미널에서 frontend를 실행합니다.

```bash
cd frontend
npm install
npm run dev
```

개발 서버 주소:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

테스트 실행:

```bash
cd backend
pytest
```

더미 데이터 삽입:

```bash
cd backend
python scripts/seed_dummy_data.py
```

더미 유저 비밀번호는 모두 `password123`입니다.
관리자 테스트 계정은 `admin@example.com` / `password123`입니다.

PostgreSQL 기준 실행 확인:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/api/posts?page=1&size=10"
```

더미 데이터가 정상 삽입되면 게시글 목록 API의 `total`이 1 이상이고, 프론트엔드 첫 화면에도 게시글이 표시됩니다. 로컬 실행에서는 `.env`의 `DATABASE_URL` host가 `localhost`인지 확인하세요.

## Docker 배포용 실행 방법

전체 서비스를 Docker로 실행하거나 배포와 유사한 환경을 확인할 때 사용합니다. Docker Compose가 PostgreSQL을 실행하고, migration을 적용한 뒤 backend와 frontend를 실행합니다.

```bash
docker compose up --build
```

서비스 구성:

- `db`: `pgvector/pgvector:pg16`
- `migrate`: `alembic upgrade head`를 한 번 실행하고 종료합니다.
- `backend`: `http://localhost:8000`에서 실행되는 FastAPI 서버
- `frontend`: `http://localhost:3000`에서 실행되는 Next.js 서버

상태 확인:

```bash
curl http://localhost:8000/health
```

컨테이너 종료:

```bash
docker compose down
```

PostgreSQL 데이터까지 삭제하려면 아래 명령을 사용합니다.

```bash
docker compose down -v
```

## API Overview

- `POST /api/auth/register`: 회원가입
- `POST /api/auth/login`: 로그인, HttpOnly JWT 쿠키 설정
- `POST /api/auth/logout`: 로그아웃, 쿠키 삭제
- `GET /api/auth/me`: 현재 사용자 조회
- `PATCH /api/users/me`: 닉네임 변경
- `GET /api/users/me/posts?page=&size=`: 내 글 목록
- `GET /api/users/me/comments?page=&size=`: 내 댓글 목록
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
- `GET /api/ai/topics`: 오늘의 토론거리 3개 카드
- `GET /api/admin/discussion-topics`: 관리자 전용 오늘의 토론거리 목록/설정 조회
- `POST /api/admin/discussion-topics/refresh`: 관리자 전용 오늘의 토론거리 재생성
- `PATCH /api/admin/discussion-topics/{topic_id}`: 관리자 전용 토론거리 고정/숨김/문구/초안 수정
- `POST /api/ai/writing-assist`: 제목/태그/카테고리/토론 질문 추천
- `POST /api/ai/editor-agent/run`: 에디터 안에서 질문 답변과 게시글 본문 생성을 처리하는 범용 Agent
- `POST /api/ai/rag/search`: RAG seed citation 데모 검색
- `POST /api/ai/rag/agent-search`: RAG 품질 개선 Agent 검색
- `POST /api/ai/external/search`: 외부 자료 MCP 호출 데모
- `POST /api/ai/agent/run`: Agent 실행 단계와 tool log 데모
- `POST /api/ai/agent/chat`: 로그인 사용자용 LangGraph 챗봇 Agent
- `POST /api/mcp`: JSON-RPC 2.0 기반 MCP 서버 엔드포인트
- `POST /api/admin/thumbnail/preview`: 관리자 전용 썸네일 생성 테스트

AI/RAG 동작:

- `OPENAI_API_KEY`가 비어 있으면 기존 로컬 데모 응답을 반환합니다.
- `OPENAI_API_KEY`가 있으면 글쓰기 보조, RAG 요약, Agent 최종 답변이 OpenAI API를 호출합니다.
- RAG embedding 생성과 검색 질의 embedding은 LangChain `OpenAIEmbeddings`를 통해 호출합니다.
- 전역 AI 챗봇은 LangGraph로 화면 맥락 준비 노드와 RAG/외부 자료 Agent 실행 노드를 연결합니다.
- 에디터 Agent는 LangGraph로 의도 분류, RAG 근거 조회, 답변/본문 생성 노드를 연결합니다.
- 게시글 작성/수정, 썸네일 후보 생성, 전역 챗봇, 에디터 Agent, AI Agent는 서버 측 Safety Layer를 먼저 통과해야 합니다. 자살·자해, 폭력/무기, 성적 요청, 혐오, 개인정보 추적, 불법행위, 고위험 의학·법률·금융 조언, 역사 주제 이탈은 RAG/외부 검색/LLM 호출 없이 안내 문구를 반환합니다.
- 역사적·교육적 맥락의 민감 주제는 허용하되, “만드는 법”, “뚫기”, “몰래 접속”, “찾아줘”처럼 실행을 돕는 위험 의도가 붙으면 차단합니다.
- AI Playground는 관리자 계정에서만 노출되는 점검 도구입니다.
- 오늘의 토론거리는 날짜별로 DB에 캐시됩니다. 캐시가 없으면 최근 게시글의 댓글 수, 조회수, 작성 시점, RAG citation을 바탕으로 생성하고, `OPENAI_API_KEY`가 있으면 LLM으로 최종 카드 문구와 글쓰기 초안을 생성합니다.
- 관리자는 `/admin/discussion-topics`에서 날짜별 추천을 재생성하거나 카드별 고정/숨김/문구/초안을 수정할 수 있습니다.
- RAG 원문 seed는 `backend/rag_seed/*.md` 파일입니다.
- 각 seed 파일은 frontmatter의 `title`, `period`, `source_url`과 본문으로 구성됩니다.
- RAG seed chunk와 embedding은 seed 파일을 기준으로 DB에 동기화됩니다.
- RAG 검색 API와 AI Playground는 `corpus` 값을 받습니다. 선택지는 `auto`, `encykorea`, `legacy`, `sinpyeon_hanguksa`, `all`입니다.
- `auto`는 일반 개괄 질의에서는 `encykorea`를 먼저 검색하고, `실록`, `원문`, `사료`, `기록` 같은 원문 지향 질의에서는 기존 실록 seed인 `legacy`를 먼저 검색합니다.
- 응답의 `searched_corpora`에서 실제 검색 대상 corpus를 확인할 수 있습니다. `sinpyeon_hanguksa`처럼 임베딩하지 않은 corpus는 명시적으로 선택하지 않는 한 자동 검색 대상에 포함하지 않습니다.
- 외부 자료 검색은 조선왕조실록 검색 결과를 파싱해 실제 기사 URL이 확인된 항목만 노출하고 tool log를 저장합니다.

MCP 서버:

- Endpoint: `POST /api/mcp`
- Protocol: JSON-RPC 2.0
- Supported methods: `initialize`, `tools/list`, `tools/call`
- Tool: `history.search_sillok`
- Tool: `image.generate_thumbnail`
- External service: 국사편찬위원회 조선왕조실록 검색 페이지를 HTTP로 호출하고 결과 기사 링크를 파싱합니다.
- External image service: `OPENAI_API_KEY`가 있으면 OpenAI Images API로 게시글 썸네일을 생성합니다. 키가 없거나 호출 실패 시 `thumbnail_url=null`로 남기고 placeholder 이미지는 만들지 않습니다.
- API key strategy: key는 `.env`에만 저장하고 Docker Compose environment로 주입합니다. 응답/log에는 key를 기록하지 않습니다. 이미지 생성은 비용이 발생할 수 있습니다.
- 관리자 계정으로 로그인하면 `/admin/thumbnail`에서 게시글 저장 없이 제목/본문/카테고리/태그 기반 썸네일 생성을 테스트할 수 있습니다.
- 글 작성 화면의 `AI 썸네일 만들기`는 저장 전 후보 3개를 생성합니다. 제목이나 본문이 너무 짧으면 생성하지 않고 보강 안내를 반환합니다.

MCP 호출 예시:

```bash
curl -X POST http://localhost:8000/api/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"history.search_sillok","arguments":{"keyword":"세종"}}}'
```

조선왕조실록 seed 수집:

```bash
cd backend
python scripts/fetch_sillok_seed.py --limit-per-record 50 --clean
```

이 스크립트는 국사편찬위원회 조선왕조실록의 공식 자료열람 페이지에서 왕대/편찬본별 앞쪽 기사 `N`건을 가져와 `backend/rag_seed/sillok/` 아래에 Markdown 파일로 저장합니다. `OPENAI_API_KEY`가 설정된 상태에서 seed를 크게 늘리면 embedding 생성 API 호출 수와 비용이 증가할 수 있습니다.

한국민족문화대백과사전 개괄 seed 수집:

```bash
cd backend
python scripts/fetch_encykorea_seed.py --delay 3 --continue-on-error
```

이 스크립트는 조선 시대 왕, 사건, 제도, 문화 관련 항목을 느린 간격으로 조회합니다. 원본 HTML과 파싱 JSON은 `backend/raw_seed/encykorea/`에 보관하고, 임베딩용 정제 Markdown은 `backend/rag_seed/overview/encykorea/`에 생성합니다. 생성된 Markdown은 `source_type=overview`, `corpus=encykorea` 메타데이터를 포함하며, 실제 embedding은 아래 명령을 실행하기 전까지 생성되지 않습니다.

RAG chunk embedding 생성:

```bash
cd backend
python scripts/embed_rag_chunks.py --sync-only
python scripts/embed_rag_chunks.py --corpus encykorea --batch-size 100
python scripts/embed_rag_chunks.py --batch-size 100
```

`--sync-only`는 seed Markdown을 DB의 `rag_documents`/`rag_chunks`까지 동기화하지만 embedding API는 호출하지 않습니다. 개괄 검색 품질을 먼저 확인할 때는 `--corpus encykorea`로 한국민족문화대백과사전 chunk만 임베딩합니다. 실제 embedding 생성에는 `OPENAI_API_KEY`가 루트 `.env`에 있어야 합니다. 이미 embedding이 있는 chunk는 건너뛰고, `embedding_json`이 비어 있는 chunk만 처리합니다.
