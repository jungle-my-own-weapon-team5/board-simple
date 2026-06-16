# 뉴스 큐레이션/중복검사 Agent 구현 계획

## Milestone 1: 계약 정리와 공통 스키마 추가 (P0)

- `docs/spec.md`의 API 계약을 기준으로 backend schema를 추가한다.
- HN preview item과 Web preview item이 공유할 `duplicate_matches` 응답 타입을 만든다.
- `DuplicateMatch` 필드는 `post_id`, `title`, `reason`, optional `score`로 고정한다.
- import 응답은 source별 id만 다르고 기존 `created/skipped` 패턴을 유지한다.
- 이 단계의 테스트는 schema validation과 기존 HN API 호환성을 우선 확인한다.

## Milestone 2: 중복검사 Agent 구현 (P0)

- `DuplicateCheckService`를 추가한다.
- URL 정규화는 scheme/host lowercase, fragment 제거, trailing slash 정리 수준으로 제한한다.
- `same_url`은 `Post.source_url` 정규화 값으로 비교한다.
- `similar_title`은 최근 게시글 최대 100개를 대상으로 `SequenceMatcher >= 0.86` 기준을 적용한다.
- `rag`는 RAG 설정이 가능할 때만 vector search를 호출하고, 실패하면 로깅 후 결과를 생략한다.
- 같은 `post_id`가 여러 기준에 걸리면 우선순위는 `same_url`, `similar_title`, `rag` 순서로 한 번만 반환한다.
- 단위 테스트로 정확 URL 중복, 제목 유사 중복, RAG 중복, RAG 실패 fallback을 검증한다.

## Milestone 3: URL 뉴스 큐레이션 Agent 구현 (P0)

- `NewsCurationService`를 추가해 URL preview 흐름을 담당한다.
- article fetch/readability/title extraction은 기존 HN 서비스 패턴을 재사용하되 HN 전용 이름과 분리한다.
- `article_text`가 요청에 있으면 테스트/수동 입력으로 간주해 외부 fetch를 건너뛴다.
- LLM prompt는 “전체 번역 금지, 한국어 요약 1문단, 핵심 포인트 3~5개 JSON” 규칙을 유지한다.
- content builder는 `## 한국어 요약`, `## 핵심 포인트`, `## 원문`, `#technews #webarticle` 형식으로 만든다.
- OpenAI 키 없음, 본문 부족, JSON 파싱 실패는 item 단위 실패 상태로 반환한다.

## Milestone 4: Backend API 연결 (P0)

- `/api/news/web/preview`와 `/api/news/web/import`를 추가한다.
- preview는 로그인 사용자만 접근 가능하고 DB 저장은 하지 않는다.
- import는 성공 item만 저장하고 `source_type/source_id` 중복이면 skip한다.
- 게시글 저장 후 태그 추출과 RAG indexing 호출은 기존 HN import 흐름을 따른다.
- RAG indexing 예외는 로깅/rollback 후 import 성공 응답을 유지한다.
- 기존 `/api/news/hacker-news/preview`에 `duplicate_matches` 계산을 붙인다.

## Milestone 5: Board MCP 서버 추가 (P1)

- Python `mcp[cli]` 의존성을 backend requirements에 추가한다.
- stdio용 `board_mcp` 서버 entrypoint를 추가하고 stdout 출력은 사용하지 않는다.
- 도구는 `preview_web_article`, `check_news_duplicates`, `preview_hacker_news`만 제공한다.
- MCP 도구는 저장 API를 호출하지 않고 preview/check 결과만 반환한다.
- README에 로컬 MCP client 설정 예시와 필요한 env를 문서화한다.

## Milestone 6: Frontend 뉴스 수집 화면 확장 (P1)

- `frontend/src/types.ts`와 `frontend/src/api/news.ts`에 Web preview/import 타입과 API 함수를 추가한다.
- 기존 `NewsImportPage`에 HN/URL 모드 전환을 추가한다.
- URL 모드에서는 URL 입력, 후보 보기, 중복 의심 게시글 링크, 선택 게시 버튼을 제공한다.
- 후보 카드 UI는 기존 HN 카드 스타일을 유지하고, 긴 제목/URL은 줄바꿈을 보장한다.
- 실패 item은 선택 불가 상태로 보여주고 오류 메시지를 한국어로 표시한다.

## Milestone 7: 통합 검증과 문서 마무리 (P1)

- backend 전체 테스트 실행: `cd backend && pytest`.
- frontend 빌드 실행: `cd frontend && npm run build`.
- README에 URL 수집, 중복검사 fallback, Board MCP 사용법을 간단히 추가한다.
- `.env.example`에는 새 secret을 추가하지 않는다. 필요한 경우 MCP 실행 예시만 문서화한다.
- 최종 요약에는 수정 파일, 테스트 결과, RAG/OpenAI 비활성화 fallback을 포함한다.

## Priority Notes

- P0는 기존 게시판 안정성, API 계약, 중복검사 정확도, import 승인 흐름이다.
- P1은 MCP 노출, 프론트 편의성, 문서화다.
- GitHub/RSS/검색/자동게시/초안저장은 이번 MVP 이후 별도 계획으로 둔다.
