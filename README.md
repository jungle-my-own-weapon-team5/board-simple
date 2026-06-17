# AI 법률 검토 보조 시스템

법률 분쟁의 사실관계와 질문을 입력하면, 공식 법령 데이터를 기반으로 관련 근거를 검색하고 쟁점을 정리한 뒤 답변 초안 작성을 보조하는 웹 애플리케이션입니다.

이 프로젝트는 기존 게시판 애플리케이션 위에 `FastAPI + PostgreSQL(pgvector) + OpenAI + 국가법령정보센터 Open API` 기반 RAG와 Agent 흐름을 단계적으로 확장한 학습형 MVP입니다. 생성 결과는 법률 자문이 아니라 법률 검토를 돕기 위한 초안 보조 결과입니다.

## 주요 기능

- 이메일/비밀번호 회원가입, 로그인, HttpOnly cookie 기반 인증
- 게시글, 댓글, 태그 기반 기본 게시판 기능
- 사실관계와 질문을 입력하는 `AI 법률 검토` 화면
- 검색 모드 선택: `집중 답변`, `쟁점 탐지`
- 법령 근거 검색 결과, 쟁점 정리, 답변 초안 병렬 표시
- PostgreSQL + pgvector 기반 법률 문서 chunk embedding 검색
- 국가법령정보센터 Open API 기반 공식 법령 데이터 조회 및 색인
- OpenAI 기반 embedding/generation provider adapter
- MCP JSON-RPC endpoint와 allowlist 기반 tool 호출 구조
- Agent 실행 이력, 검색 근거, citation 검증을 위한 audit 저장 구조

## 현재 구현 범위

현재 UI의 자동 수집 및 색인 흐름은 `법령` 중심입니다. 법령 범위에는 법률, 대통령령, 총리령, 부령 계열이 포함될 수 있습니다.

판례, 해석례, 행정심판례, 사용자 업로드 문서, 메모는 데이터 모델과 API 확장을 고려해 설계되어 있으나, 발표용 MVP 화면에서는 후속 지원 대상으로 표시합니다.

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| Frontend | Next.js App Router, React, TypeScript, Tailwind CSS, shadcn/ui, Zustand |
| Backend | FastAPI, Pydantic, SQLAlchemy, Alembic |
| Database | PostgreSQL 17, pgvector |
| AI/RAG | OpenAI provider adapter, embedding profile, pgvector similarity search |
| External API | 국가법령정보센터 Open API |
| Agent/MCP | FastAPI 내부 MCP JSON-RPC endpoint, bounded Orchestrator Agent |
| Container | Docker, Docker Compose |

## 시스템 구조

```text
사용자
  -> Next.js frontend
  -> FastAPI backend
  -> RAG / Agent / MCP services
  -> PostgreSQL + pgvector
  -> OpenAI API / 국가법령정보센터 Open API
```

시각화 자료:

- 전체 시스템 아키텍처: [Mermaid](docs/diagrams/system-architecture.mmd) / [draw.io](docs/diagrams/system-architecture.drawio)
- RAG/Agent 처리 흐름: [Mermaid](docs/diagrams/rag-agent-flow.mmd) / [draw.io](docs/diagrams/rag-agent-flow.drawio)
- 발표용 배포 토폴로지: [Mermaid](docs/diagrams/deployment-topology.mmd) / [draw.io](docs/diagrams/deployment-topology.drawio)

상세 소개:

- [시스템 소개 문서](docs/system-overview.md)
- [아키텍처 설계](docs/architecture.md)
- [RAG Pipeline 설계](docs/rag-pipeline.md)
- [MCP/Agent 설계](docs/mcp-agent-design.md)
- [API 명세](docs/api-spec.md)

## 빠른 실행

루트에 `.env`를 준비합니다. 실제 secret 값은 커밋하지 않습니다.

```powershell
Copy-Item .env.example .env
```

Docker Compose로 전체 스택을 실행합니다.

```powershell
docker compose up --build
```

기본 주소:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- Backend health check: `http://localhost:8000/health`

컨테이너 종료:

```powershell
docker compose down
```

데이터베이스 볼륨까지 제거:

```powershell
docker compose down -v
```

## 로컬 개발 실행

Backend:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

## 검증 명령

Backend:

```powershell
cd backend
pytest
```

Frontend:

```powershell
cd frontend
npx tsc --noEmit --pretty false
```

## 보안 원칙

- `.env`와 secret 값은 커밋하지 않습니다.
- `OPENAI_API_KEY`, `LAW_OPEN_API_OC`, JWT secret 등은 환경변수에서만 읽습니다.
- secret, 인증 cookie, raw JWT, 전체 private dispute facts는 로그에 남기지 않는 것을 원칙으로 합니다.
