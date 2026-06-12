# Board Simple

## Branch Strategy

- `main`: 메인 브랜치입니다. `README.md`를 포함한 최소 파일/폴더만 존재합니다.
- `dev`: 프로젝트에서 사용할 기반 프로젝트까지만 구현한 브랜치입니다.
- `project/{nickname}`: 각자 사용할 브랜치입니다. 기반 프로젝트에 기반하여 AI를 활용한 추가 기능들을 붙인 프로젝트입니다.

React + TypeScript + Vite 프론트엔드와 FastAPI 백엔드로 구성한 기본 게시판입니다.

## Features

- 이메일/비밀번호 회원가입, 로그인, 로그아웃
- HttpOnly 쿠키 기반 JWT 인증
- 닉네임 unique 검증과 `익명0000` 형식 자동 닉네임 생성
- 게시글 CRUD, Markdown 작성/미리보기/표시
- 댓글 작성과 `View more` 방식 페이지네이션
- `#태그명` 형식 태그 추출
- 게시글 제목 검색과 페이지네이션

## Project Structure

```text
.
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   ├── package.json
│   └── .env.example
└── README.md
```

## Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

`backend/.env`:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
JWT_SECRET_KEY=change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
FRONTEND_ORIGIN=http://localhost:5173
```

Supabase PostgreSQL connection string을 `DATABASE_URL`에 넣습니다. 운영 환경에서는 JWT 쿠키의 `secure=True` 설정을 적용해야 합니다.

마이그레이션과 실행:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

테스트:

```bash
pytest
```

## Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

`frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

빌드:

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
