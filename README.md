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
- 댓글 작성과 `View more` 방식 페이지네이션
- `#태그명` 형식 태그 추출
- 게시글 제목 검색과 페이지네이션
- `역사 덕담` 기획 기반 글 유형/카테고리, 조회수, 댓글 수 표시
- 오늘의 토론거리, AI 글쓰기 보조, RAG/MCP/Agent 데모 API와 AI Playground
- `OPENAI_API_KEY` 설정 시 OpenAI Responses API와 Embeddings API 기반 AI/RAG 실행

## Stack

- FE: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui, zustand
- BE: FastAPI, Pydantic, SQLAlchemy, Alembic
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
NATIONAL_LIBRARY_API_KEY=
```

전체 Docker 실행에서는 backend가 Docker Compose 네트워크 안에서 실행됩니다. 이 경우 DB host는 `db`를 사용합니다.

```env
DATABASE_URL=postgresql+psycopg://board:board@db:5432/board
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
- `POST /api/ai/writing-assist`: 제목/태그/카테고리/토론 질문 추천
- `POST /api/ai/rag/search`: RAG seed citation 데모 검색
- `POST /api/ai/external/search`: 외부 자료 MCP 호출 데모
- `POST /api/ai/agent/run`: Agent 실행 단계와 tool log 데모

AI/RAG 동작:

- `OPENAI_API_KEY`가 비어 있으면 기존 로컬 데모 응답을 반환합니다.
- `OPENAI_API_KEY`가 있으면 글쓰기 보조, RAG 요약, Agent 최종 답변이 OpenAI API를 호출합니다.
- RAG seed chunk embedding은 `OPENAI_EMBEDDING_MODEL`로 생성되어 DB에 저장됩니다.
- 외부 자료 검색은 조선왕조실록 검색 링크를 호출하고 tool log를 저장합니다.
