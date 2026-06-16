# Vector DB 연관 글 구현 계획

## Milestone 1: 응답 계약과 테스트 기준 고정 (P0)

- `GET /api/posts/{post_id}/related` 응답 스키마를 추가하고, 항목은 `post_id`, `title`, `score`로 고정한다.
- 목록 API(`GET /api/posts`)와 게시글 상세 API(`GET /api/posts/{post_id}`)는 기존 CRUD 계약을 깨지 않는다.
- RAG가 불가해도 related API는 200 응답과 빈 배열을 반환하는 테스트를 먼저 추가한다.
- fake RAG service 또는 fake vector store로 SQLite 테스트가 pgvector/OpenAI/네트워크를 요구하지 않게 한다.

## Milestone 2: RAG 서비스 연관 글 검색 구현 (P0)

- `RagService`에 현재 게시글 기준 연관 글 조회 메서드를 추가한다.
- query text는 `Title: {title}\n\n{content}` 형태로 기존 인덱싱 문서와 맞춘다.
- `similarity_search_with_score`는 표시 개수보다 넉넉히 요청해 자기 자신과 중복 chunk 제거 후 최대 3개를 확보한다.
- 결과 처리 규칙:
  - metadata `post_id`가 없으면 제외한다.
  - 현재 게시글 id는 제외한다.
  - 같은 post_id는 첫 결과만 사용한다.
  - DB에 없는 게시글은 제외한다.
  - metadata title이 비어 있으면 DB의 `Post.title`을 사용한다.
- RAG 비활성화, OpenAI 키 없음, vector store 예외는 로깅 후 빈 목록으로 반환한다.

## Milestone 3: 게시글 상세 API 연결 (P0)

- `GET /api/posts/{post_id}/related`에서 기존 `get_post_or_404`로 현재 게시글 존재를 확인한 뒤 연관 글을 반환한다.
- 생성/수정/상세 응답은 기존 `PostRead` 계약을 유지하고, related API가 별도 목록을 제공한다.
- 기존 CRUD 훅(`sync_post_index`, `delete_post_index_safe`)은 변경하지 않는다.
- HN import나 OpenAI 설정 실패가 게시글 CRUD를 깨지 않는 기존 정책을 유지한다.

## Milestone 4: 백엔드 검증 강화 (P0)

- 서비스 단위 테스트로 자기 자신 제외, 중복 제거, 최대 3개 제한을 검증한다.
- API 테스트로 related API 응답 형태와 장애 시 빈 배열 fallback을 검증한다.
- 기존 `test_auth_posts_comments.py`, `test_hacker_news.py`가 계속 통과하는지 확인한다.
- 검증 명령은 `cd backend && pytest`를 사용한다.

## Milestone 5: 프론트 타입과 상세 UI (P1)

- `frontend/src/types.ts`에 `RelatedPost` 타입을 추가한다.
- `PostDetailPage`에서 related API를 호출하고, 본문 아래, 댓글 위에 `연관 글` 섹션을 추가한다.
- 연관 글 항목은 제목 링크만 표시하고, score나 excerpt는 화면에 노출하지 않는다.
- 빈 배열이면 섹션을 렌더링하지 않는다.
- 긴 제목은 `[overflow-wrap:anywhere]` 등 기존 패턴으로 레이아웃을 보호한다.

## Milestone 6: 최종 검증과 문서 정리 (P1)

- 백엔드 전체 테스트를 실행한다: `cd backend && pytest`.
- 프론트 타입/빌드 검증을 실행한다: `cd frontend && npm run build`.
- README 또는 운영 문서에는 RAG가 비활성화되면 연관 글이 숨겨진다는 점만 간단히 기록한다.
- 변경 요약에는 수정 파일, 테스트 결과, RAG 비활성화 fallback 동작을 포함한다.

## Priority Notes

- P0는 API 계약, 장애 격리, 기존 CRUD 보존을 위해 먼저 끝낸다.
- P1은 사용자 화면과 문서 마무리다.
- 새 DB 구조, background worker, reranking은 MVP 범위에서 제외한다.
