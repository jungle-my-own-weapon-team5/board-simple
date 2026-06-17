# MCP Preview 자동 중복 판정 한줄평 스펙

## Summary

- MCP preview tool이 `duplicate_matches`를 만든 직후 자동으로 중복 판정을 실행한다.
- preview 결과에 `duplicate_judgements` 필드를 추가해 RAG 유사 중복 의심에 대한 한줄평을 바로 제공한다.
- 대상 tool은 `preview_hacker_news_tool`과 `preview_web_article_tool`이다.
- 기존 `duplicate_matches` 필드와 별도 `judge_news_duplicates_tool`은 유지한다.
- 저장, 게시, import, RAG indexing은 하지 않는다.

## MCP Response Behavior

- `duplicate_matches`가 비어 있으면 `duplicate_judgements: []`를 반환한다.
- `duplicate_matches`가 있으면 기존 `DuplicateJudgementService`를 호출해 판정 결과를 붙인다.
- `duplicate_judgements` item shape:

```json
{
  "post_id": 60,
  "title": "기존 게시글 제목",
  "verdict": "uncertain",
  "confidence": null,
  "reason": "벡터 검색상 유사하지만 실제 중복 여부는 확인이 필요합니다."
}
```

- `reason`이 agent가 바로 읽을 한줄평이다.
- OpenAI 미설정 또는 LLM 실패 시 기존 conservative fallback 한줄평을 반환한다.
- 기존 preview/check MCP tool의 기존 필드는 제거하거나 이름 변경하지 않는다.

## Implementation

- `backend/app/mcp/board.py`에 helper를 추가한다.
  - `_judgements_for_candidate(db, client_id, title, url, summary, key_points, duplicate_matches) -> list[dict]`
  - `duplicate_matches`가 없으면 빈 list를 반환한다.
  - 있으면 `NewsDuplicateJudgementItem`을 만들고 `get_duplicate_judgement_service().judge(db, [item])`을 호출한다.
  - 첫 응답 item의 `results`를 `model_dump()`로 반환한다.
- `preview_web_article_tool`
  - `_candidate_dict(item)` 결과에 `duplicate_judgements`를 추가한다.
  - `client_id`는 `web-{item.source_id}`를 사용한다.
- `preview_hacker_news_tool`
  - 각 candidate dict에 `duplicate_matches`와 `duplicate_judgements`를 함께 넣는다.
  - `client_id`는 `hn-{candidate.hn_id}`를 사용한다.
- `judge_news_duplicates_tool`
  - 유지한다. 수동 재판정이나 외부 agent 직접 호출용이다.

## Tests

- MCP web preview 테스트:
  - 기존 게시글을 넣어 `duplicate_matches`가 생기게 한다.
  - `preview_web_article_tool` 결과에 `duplicate_judgements`가 포함되는지 검증한다.
  - OpenAI 없이 fallback 한줄평이 반환되는지 검증한다.
- MCP HN preview 테스트:
  - fake HN service가 성공 candidate를 반환하게 한다.
  - 기존 게시글과 매칭되어 `duplicate_matches`와 `duplicate_judgements`가 함께 반환되는지 검증한다.
- 빈 중복 의심 케이스:
  - `duplicate_matches=[]`이면 `duplicate_judgements=[]`.
- 회귀:
  - 기존 `judge_news_duplicates_tool` 테스트는 유지한다.
  - 검증 명령: `cd backend && ./.venv/bin/python -m pytest`

## Assumptions

- “한줄평”은 `DuplicateJudgementResult.reason`을 의미한다.
- 자동 판정은 MCP preview tool에만 적용하고 웹 UI preview API는 변경하지 않는다.
- 판정 결과는 advisory이며 자동 게시/자동 차단에 쓰지 않는다.
- 새 DB 테이블, migration, background worker, admin UI는 추가하지 않는다.
