# 뉴스 큐레이션/중복검사 Agent + Board MCP 스펙

## Summary

- 백엔드 내부 Agent 서비스로 기술 뉴스 후보를 만들고, 운영자가 승인한 후보만 게시글로 저장한다.
- MVP 뉴스 소스는 기존 Hacker News와 운영자가 직접 입력한 웹 기사 URL이다.
- 중복검사 Agent는 기존 게시글과 RAG/vector 데이터를 활용해 이미 가져온 기사나 유사한 글을 표시한다.
- Board MCP는 AI 클라이언트가 후보 생성과 중복검사를 호출할 수 있는 읽기/후보 전용 도구 표면으로 제공한다.
- 새 저장 테이블이나 마이그레이션은 추가하지 않고 기존 `posts.source_*` 메타데이터를 재사용한다.

## User Experience

- 기존 `/news/import` 화면을 확장해 `Hacker News` 모드와 `URL` 모드를 제공한다.
- HN 모드는 현재처럼 source, query, limit으로 후보를 수집한다.
- URL 모드는 기사 URL을 입력하면 본문 추출, 한국어 요약, 핵심 포인트, 중복 의심 결과를 보여준다.
- 성공 후보만 선택 가능하며, 사용자가 선택한 항목만 게시한다.
- 중복 의심 결과는 후보 카드 안에 기존 게시글 제목 링크로 보여준다.
- RAG가 꺼져 있거나 실패해도 URL/제목 기반 중복 결과와 후보 preview는 계속 표시한다.

## Backend API

### `POST /api/news/hacker-news/preview`

- 기존 요청 형식은 유지한다: `{ "source": "top|best|new|search", "query"?: string, "limit": number }`.
- 각 item에 `duplicate_matches`를 추가한다.
- HN 수집, 기사 fetch, 요약 실패는 기존처럼 item 단위 `summary_status="failed"`로 반환한다.

### `POST /api/news/web/preview`

- 요청:

```json
{
  "url": "https://example.com/article",
  "article_text": "optional test/operator supplied article text"
}
```

- 응답:

```json
{
  "item": {
    "source_type": "web_article",
    "source_id": "normalized-url-hash",
    "title": "원문 제목",
    "url": "https://example.com/article",
    "summary_status": "success",
    "summary": "한국어 요약",
    "key_points": ["핵심 포인트"],
    "duplicate_matches": [
      { "post_id": 1, "title": "기존 글", "reason": "same_url", "score": null }
    ],
    "error": null
  }
}
```

- `article_text`는 테스트와 수동 보정용이다. 제공되면 외부 fetch 대신 사용한다.
- `OPENAI_API_KEY`가 없거나 요약에 실패하면 `summary_status="failed"`와 `error`를 반환한다.

### `POST /api/news/web/import`

- 성공 preview item 목록을 받아 게시글로 저장한다.
- 저장 메타데이터:
  - `source_type="web_article"`
  - `source_id=sha256(normalized_url)[:32]`
  - `source_url=url`
  - `source_title=title`
  - `source_fetched_at=now`
- 이미 같은 `source_type/source_id`가 있으면 `already_imported`로 skip한다.
- RAG indexing 실패는 로깅하고 import 성공을 유지한다.

## Agent Behavior

- `NewsCurationService`는 기사 본문 추출, 제목 추출, 한국어 요약, 후보 item 생성을 담당한다.
- `DuplicateCheckService`는 다음 기준으로 중복 후보를 만든다.
  - `same_url`: normalized URL이 기존 `Post.source_url`과 일치
  - `similar_title`: 최근 게시글 제목과 `SequenceMatcher` 유사도 `0.86` 이상
  - `rag`: RAG가 설정된 경우 후보 제목+요약으로 기존 vector DB 검색
- 중복 결과는 같은 `post_id`를 한 번만 반환한다.
- RAG/vector search 실패는 중복검사 전체 실패가 아니라 `rag` 결과 생략으로 처리한다.
- 전체 기사 번역문이나 원문 전문은 저장하지 않는다.

## Board MCP

- Python MCP SDK의 `FastMCP` 기반 stdio 서버를 추가한다.
- stdout 로그는 금지하고 logging/stderr만 사용한다.
- 제공 도구:
  - `preview_web_article(url, article_text=None)`
  - `check_news_duplicates(title, url=None, content=None)`
  - `preview_hacker_news(source, query=None, limit=10)`
- MCP 도구는 게시글 저장을 하지 않는다.
- 게시 저장은 로그인된 웹 UI에서만 수행한다.

## Tests

- SQLite 테스트는 pgvector, OpenAI, 외부 네트워크 없이 fake fetcher, fake readability, fake LLM, fake vector store로 검증한다.
- URL preview 로그인 요구, 성공 응답, 요약 실패 응답을 검증한다.
- URL import 생성, 중복 skip, RAG indexing 실패 생존을 검증한다.
- 중복검사 Agent의 URL 일치, 제목 유사도, RAG 결과 dedupe, RAG 실패 fallback을 검증한다.
- HN preview 기존 동작과 `duplicate_matches` 추가를 검증한다.
- 검증 명령:
  - `cd backend && pytest`
  - `cd frontend && npm run build`

## Assumptions

- `RAG_ENABLED=false` 기본값은 유지한다.
- GitHub 릴리즈 수집, RSS, 웹 검색, 자동 게시, 초안 저장, 스케줄링, 백그라운드 워커는 MVP에서 제외한다.
- OpenAI 키가 없어도 기존 게시판 CRUD와 기존 게시글 조회는 정상 동작해야 한다.
- 사용자-facing copy는 기존 UI와 맞춰 한국어를 우선한다.
