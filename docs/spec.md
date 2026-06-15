# 기술 뉴스 RAG Q&A 스펙

## Summary

- 기존 게시글(`posts`)을 기술 뉴스 원문으로 보고, 전체 게시글 기반 Q&A 기능을 추가한다.
- LangChain, OpenAI API, PostgreSQL pgvector를 사용한다.
- 게시글 생성, 수정, 삭제 시 RAG 인덱스를 즉시 갱신한다.
- 기존 게시글은 재색인 스크립트로 한 번 백필한다.

## User Experience

- 사용자는 별도 `/ask` 화면에서 전체 뉴스 게시글을 대상으로 질문한다.
- 답변은 검색된 게시글 context만 근거로 생성한다.
- 답변 아래에는 출처 게시글 링크, 제목, 발췌문, 유사도 점수를 표시한다.
- 검색된 context에 답이 없으면 추측하지 않고 모른다고 답한다.

## Backend API

### `POST /api/rag/ask`

Request:

```json
{
  "question": "최근 AI 반도체 관련 이슈를 요약해줘"
}
```

Response:

```json
{
  "answer": "검색된 뉴스 기준 답변",
  "sources": [
    {
      "post_id": 1,
      "title": "게시글 제목",
      "excerpt": "검색에 사용된 발췌문",
      "score": 0.21
    }
  ]
}
```

Validation:

- `question`은 공백 제외 1자 이상이어야 한다.
- 과도하게 긴 질문은 422로 거절한다.

## Environment

- `OPENAI_API_KEY`: OpenAI API 키. 코드나 로그에 노출하지 않는다.
- `OPENAI_CHAT_MODEL`: 기본 `gpt-5.5`.
- `OPENAI_EMBEDDING_MODEL`: 기본 `text-embedding-3-large`.
- `RAG_ENABLED`: 기본 `false`. 실제 사용 시 `.env`에서 `true`.
- `RAG_COLLECTION_NAME`: 기본 `tech_news_posts`.
- `RAG_TOP_K`: 기본 `5`.

## Data Model

- LangChain `PGVector`는 기존 `DATABASE_URL`을 사용한다.
- `pgvector` extension은 기존 `0002_enable_pgvector` migration을 유지한다.
- `post_rag_chunks` 테이블을 추가해 게시글과 LangChain document id를 매핑한다.
- 각 chunk metadata에는 `post_id`, `title`, `author_id`, `created_at`, `chunk_index`를 저장한다.

## Indexing Behavior

- 게시글 생성 시 제목과 본문을 chunking 후 벡터스토어에 추가한다.
- 게시글 수정 시 기존 chunk id를 삭제하고 새 chunk를 추가한다.
- 게시글 삭제 시 해당 게시글의 chunk id를 삭제한다.
- RAG 인덱싱 실패가 게시글 CRUD 자체를 실패시키지 않도록 서비스 레이어에서 격리한다.
- 기존 게시글 백필 명령은 `python -m app.scripts.reindex_rag`로 제공한다.

## RAG Behavior

- `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)`를 사용한다.
- 질문 시 `RAG_TOP_K`만큼 유사 chunk를 검색한다.
- prompt는 retrieved context를 데이터로만 취급하도록 명시한다.
- context 안의 지시문은 무시하고, 답이 없으면 모른다고 답하게 한다.

## Frontend

- `/ask` 페이지를 추가한다.
- 상단 내비게이션에 Q&A 링크를 추가한다.
- 질문 textarea, submit 버튼, loading, error, answer, source list 상태를 구현한다.
- source item은 `/posts/{post_id}`로 이동할 수 있어야 한다.

## Tests

- 기존 게시글/댓글 테스트는 RAG 비활성 상태에서 그대로 통과해야 한다.
- fake embedding, fake vector store, fake LLM을 주입해 `/api/rag/ask` 응답 형식을 검증한다.
- 게시글 생성, 수정, 삭제 시 chunk 매핑이 생성, 교체, 삭제되는지 검증한다.
- 프론트는 build로 타입 오류를 확인한다.

## Assumptions

- 별도 뉴스 테이블은 만들지 않고 현재 `posts` 테이블을 뉴스 게시판으로 사용한다.
- Q&A는 MVP에서 비로그인 사용자도 사용할 수 있다.
- 큐나 워커는 도입하지 않고 CRUD 시 즉시 인덱싱한다.
- LangChain 공식 패키지인 `langchain-postgres`, `langchain-openai`를 사용한다.
