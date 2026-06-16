# Vector DB 기반 연관 글 제목 목록 스펙

## Summary

- 게시글 상세 화면에서 현재 게시글과 의미적으로 가까운 게시글 제목 목록을 보여준다.
- 연관도 계산은 기존 RAG 인덱스의 vector DB 값을 사용한다.
- 새 테이블이나 별도 저장소를 만들지 않고, `PGVector` 문서 metadata의 `post_id`, `title`을 재사용한다.
- RAG/vector 설정이 없거나 검색이 실패해도 기존 게시글 조회와 CRUD는 정상 동작해야 한다.

## User Experience

- 사용자는 게시글 상세 화면(`/posts/{postId}`)에서 본문 아래, 댓글 위에 `연관 글` 섹션을 본다.
- 연관 글은 제목만 링크로 표시한다.
- 제목을 클릭하면 해당 게시글 상세 화면으로 이동한다.
- 연관 글이 없거나 RAG를 사용할 수 없으면 섹션을 숨긴다.
- 게시글 목록 화면에는 연관 글을 표시하지 않는다.

## Backend API

### `GET /api/posts/{post_id}/related`

현재 게시글과 의미적으로 가까운 게시글 제목 목록을 반환한다.

```json
[
  {
    "post_id": 2,
    "title": "연관 게시글 제목",
    "score": 0.12
  }
]
```

Rules:

- 응답은 항상 배열이다.
- 최대 3개까지 반환한다.
- 현재 게시글 자신은 제외한다.
- 같은 게시글의 여러 chunk가 검색되면 하나만 반환한다.
- `score`는 vector store가 제공하면 포함하고, 없으면 `null`로 둔다.
- RAG 비활성화, OpenAI 키 없음, vector store 오류, metadata 누락은 빈 배열로 처리한다.
- `GET /api/posts` 목록 API와 `GET /api/posts/{post_id}` 상세 API 응답은 기존 CRUD 계약을 깨지 않는다.

## Related Post Retrieval

- 현재 게시글의 제목과 본문을 query text로 사용한다.
- 기존 `RagService`에 연관 글 조회 메서드를 추가한다.
- 내부 검색은 `similarity_search_with_score`를 사용한다.
- 중복 제거와 자기 자신 제외를 위해 검색 개수는 표시 개수보다 크게 요청한다.
- metadata에서 `post_id`가 없는 결과는 무시한다.
- metadata의 `title`이 없거나 빈 문자열이면 DB에서 해당 게시글 제목을 조회해 보정한다.
- DB에 존재하지 않거나 삭제된 게시글은 결과에서 제외한다.

## Backend Integration

- related endpoint는 기존 게시글 조회 후 연관 글을 계산해 별도 배열로 반환한다.
- 생성/수정/삭제 시 기존 `sync_post_index`, `delete_post_index_safe` 흐름은 유지한다.
- RAG 인덱싱 실패가 게시글 CRUD를 깨지 않아야 하는 기존 정책을 유지한다.
- SQLite 테스트는 pgvector, OpenAI, 외부 네트워크 없이 fake vector store와 fake RAG service로 검증한다.

## Frontend

- `frontend/src/types.ts`에 `RelatedPost` 타입을 추가한다.
- `PostDetailPage`는 related API 응답이 있을 때만 `연관 글` 섹션을 렌더링한다.
- UI는 기존 shadcn/Tailwind 스타일과 맞춘다.
- 사용자-facing copy는 한국어를 우선한다.
- 제목은 긴 문자열에서도 줄바꿈되어 레이아웃을 깨지 않아야 한다.

## Tests

- related API가 연관 글 배열을 반환하는지 검증한다.
- fake vector store 결과에서 현재 게시글 제외, post_id 중복 제거, 최대 3개 제한을 검증한다.
- RAG 비활성화 또는 vector 오류가 related API를 실패시키지 않고 빈 배열을 반환하는지 검증한다.
- 기존 게시글 CRUD, 댓글, RAG Q&A 테스트가 계속 통과해야 한다.
- 검증 명령:
  - `cd backend && pytest`
  - `cd frontend && npm run build`

## Assumptions

- 표시 위치는 게시글 상세 화면만이다.
- 연관 글 개수는 최대 3개다.
- 새 migration은 만들지 않는다.
- 연관 글은 상세 화면에서만 호출되는 별도 endpoint로 제공한다.
- MVP 범위에 reranking, chat history, scheduling, admin UI는 포함하지 않는다.
