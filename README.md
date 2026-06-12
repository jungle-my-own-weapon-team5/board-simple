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
- `#태그명` 형식 태그 추출
- 게시글 제목 검색과 페이지네이션

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

## Environment

Use a root `.env` file for local and Docker Compose configuration.

```bash
cp .env.example .env
```

Required values are documented in `.env.example`. For local Docker defaults, the example values are enough.

## Docker Compose

```bash
docker compose up --build
```

Services:

- `db`: `pgvector/pgvector:pg16`
- `migrate`: runs `alembic upgrade head`
- `backend`: FastAPI on `http://localhost:8000`
- `frontend`: Next.js on `http://localhost:3000`

Health check:

```bash
curl http://localhost:8000/health
```

## Backend Local Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

On Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Test:

```bash
cd backend
pytest
```

## Frontend Local Setup

```bash
cd frontend
npm install
npm run dev
```

Build:

```bash
npm run build
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
