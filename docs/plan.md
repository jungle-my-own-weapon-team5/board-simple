# 기술 뉴스 RAG Q&A 구현 계획

## Milestone 0: 기준선 확인 (P0)

- 현재 테스트와 빌드 상태를 먼저 확인한다.
- `backend/requirements.txt`, `backend/requirements-dev.txt`, `frontend/package.json`의 실행 방식을 유지한다.
- 확인 명령:
  - `cd backend && pytest`
  - `cd frontend && npm run build`

## Milestone 1: 설정과 의존성 추가 (P0)

- 백엔드에 LangChain 관련 의존성을 추가한다.
  - `langchain`
  - `langchain-openai`
  - `langchain-postgres`
  - `langchain-text-splitters`
- `Settings`에 RAG/OpenAI 환경변수를 추가한다.
- `.env.example`, `docker-compose.yml`, `README.md`에 필요한 환경변수를 문서화한다.
- `RAG_ENABLED=false`일 때 기존 기능이 영향받지 않아야 한다.

## Milestone 2: RAG 저장 구조 추가 (P0)

- `post_rag_chunks` 모델과 migration을 추가한다.
- 컬럼:
  - `id`
  - `post_id`
  - `document_id`
  - `created_at`
- `post_id`는 `posts.id`를 참조하고 게시글 삭제 시 cascade 처리한다.
- 같은 게시글의 기존 chunk document id를 삭제하고 재생성할 수 있어야 한다.

## Milestone 3: RAG 서비스 구현 (P0)

- `app/services/rag.py`를 추가한다.
- 책임:
  - OpenAI embeddings와 chat model 생성
  - PGVector vector store 생성
  - 게시글을 LangChain `Document`로 변환
  - chunking
  - index, reindex, delete
  - ask 질의 처리
- 인덱싱 실패는 로깅하고 게시글 CRUD 응답은 유지한다.
- 질문 답변은 retrieved context만 사용하고 출처 metadata를 response로 반환한다.

## Milestone 4: 게시글 CRUD 연동 (P0)

- `create_post` 성공 후 RAG index를 생성한다.
- `update_post` 성공 후 해당 게시글의 기존 chunk를 삭제하고 새로 index한다.
- `delete_post` 전에 해당 게시글의 chunk를 삭제한다.
- RAG 비활성 상태에서는 no-op으로 동작한다.

## Milestone 5: Q&A API 추가 (P0)

- `app/api/rag.py`를 추가하고 `main.py`에 router를 등록한다.
- Pydantic schema를 추가한다.
  - `RagAskRequest`
  - `RagSource`
  - `RagAskResponse`
- `POST /api/rag/ask`를 구현한다.
- `RAG_ENABLED=false` 또는 `OPENAI_API_KEY` 없음은 명확한 503 오류로 처리한다.

## Milestone 6: 백필 스크립트 추가 (P1)

- `app/scripts/reindex_rag.py`를 추가한다.
- 전체 게시글을 순회해 기존 chunk mapping을 삭제하고 새로 색인한다.
- 실행 전 `RAG_ENABLED=true`와 `OPENAI_API_KEY`가 필요하다.
- README에 실행 방법을 추가한다.

## Milestone 7: 프론트 Q&A 화면 추가 (P1)

- `frontend/src/api/rag.ts`를 추가한다.
- `frontend/src/types.ts`에 RAG request/response 타입을 추가한다.
- `/ask` 라우트와 `AskPage` 화면을 추가한다.
- 상단 내비게이션에 Q&A 링크를 추가한다.
- 답변, 오류, loading, 출처 링크 상태를 구현한다.

## Milestone 8: 테스트와 검증 (P0)

- 백엔드 테스트:
  - RAG 비활성 상태에서 기존 테스트 통과
  - ask API validation
  - fake RAG service를 통한 응답 형식 검증
  - CRUD 연동 시 service 호출 검증
- 프론트 검증:
  - `npm run build`
- Docker 검증:
  - `docker compose up --build`
  - `python -m app.scripts.reindex_rag`
  - `/ask`에서 실제 게시글 기반 답변과 출처 확인

## Priority Notes

- P0는 기능의 정확성과 기존 게시판 안정성을 위해 반드시 먼저 끝낸다.
- P1은 실제 운영 편의성과 사용자 경험을 위한 후속 작업이다.
- streaming, 대화 히스토리, reranking, 관리자 전용 재색인 UI는 이번 MVP 범위에서 제외한다.
