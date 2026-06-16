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
- 게시글 CRUD, Markdown 작성/미리보기/표시
- 댓글 작성과 `View more` 방식 페이지네이션
- 별도 입력 필드 기반 게시글 태그 관리
- 게시글 제목 검색과 페이지네이션
- 게시글 RAG 청크 인덱싱과 로그인 사용자용 AI 검색 챗봇

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

로컬 개발에서는 PostgreSQL만 Docker로 실행하고, backend/frontend는 내 컴퓨터에서 직접 실행합니다. 이 경우 backend가 호스트 OS에서 실행되므로 `DATABASE_URL`은 호스트 포트 `5433`을 사용합니다.

```env
DATABASE_URL=postgresql+psycopg://board:board@localhost:5433/board
```

전체 Docker 실행에서는 backend가 Docker Compose 네트워크 안에서 실행됩니다. 이 경우 Compose가 backend/migrate 컨테이너에 `DOCKER_DATABASE_URL` 값을 `DATABASE_URL`로 주입하며, DB host는 Compose 서비스명인 `db`를 사용합니다.

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
- `POST /api/rag/chat`: 로그인 사용자용 게시글 RAG 챗봇

## RAG 설정

RAG 챗봇은 OpenAI API와 PostgreSQL pgvector를 사용합니다.

```env
OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MODEL=gpt-5.5
RAG_TOP_K=5
```

기존 게시글을 인덱싱하려면 migration 적용 후 backend에서 아래 명령을 실행합니다.

```bash
python -m app.rag.backfill --all
```
