# MCP Preview 자동 중복 판정 한줄평 구현 계획

## Milestone 1: Preview 판정 helper 추가 (P0)

- `backend/app/mcp/board.py`에 `_judgements_for_candidate(...) -> list[dict]` helper를 추가한다.
- 입력은 DB session, `client_id`, 후보 제목/URL/요약/핵심 포인트, `duplicate_matches`로 한다.
- `duplicate_matches`가 비어 있으면 `[]`를 즉시 반환한다.
- match가 있으면 `NewsDuplicateJudgementItem`을 생성하고 `get_duplicate_judgement_service().judge(db, [item])`을 호출한다.
- 반환은 첫 response item의 `results`를 `model_dump()`한 list로 한다.

## Milestone 2: MCP preview tools에 자동 한줄평 추가 (P0)

- `preview_web_article_tool`에서 `_candidate_dict(item)` 결과에 `duplicate_judgements`를 추가한다.
- web preview의 `client_id`는 `web-{item.source_id}`로 고정한다.
- `preview_hacker_news_tool`에서 각 candidate의 `duplicate_matches` 계산 직후 `duplicate_judgements`를 추가한다.
- HN preview의 `client_id`는 `hn-{candidate.hn_id}`로 고정한다.
- 기존 `duplicate_matches`, 원문 링크, 요약, key points, HN metadata 필드는 유지한다.
- 별도 `judge_news_duplicates_tool`은 유지하고 동작을 변경하지 않는다.

## Milestone 3: Backend MCP 테스트 추가/수정 (P0)

- web preview MCP 테스트를 추가한다.
- fake `NewsCurationService` 또는 monkeypatch로 외부 fetch/LLM 없이 성공 web candidate를 만든다.
- 기존 게시글과 같은 URL을 넣어 `same_url` duplicate match와 fallback `duplicate_judgements`를 검증한다.
- HN preview MCP 테스트를 추가한다.
- fake `HackerNewsService`로 성공 candidate를 반환하고 기존 게시글과 매칭되게 한다.
- `duplicate_matches=[]`인 preview 결과는 `duplicate_judgements=[]`인지 검증한다.
- 기존 `judge_news_duplicates_tool` 테스트는 그대로 통과해야 한다.

## Milestone 4: 회귀 검증 (P1)

- backend 전체 테스트를 실행한다: `cd backend && ./.venv/bin/python -m pytest`.
- 프론트 변경은 없으므로 `npm run build`는 필수 실행 대상이 아니다.
- 최종 보고에는 자동 추가 필드명, client_id 규칙, fallback 한줄평 동작, 검증 결과를 포함한다.

## Priority Notes

- P0: preview 자동 판정 helper, web/HN preview 응답 확장, SQLite 테스트.
- P1: 전체 backend 회귀 확인.
- 제외: 웹 UI API 변경, preview tool 기존 필드 제거, DB 저장, migration, background worker.
