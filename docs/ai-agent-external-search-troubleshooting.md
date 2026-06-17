# AI Agent 외부 검색 품질 트러블슈팅

작성일: 2026-06-18

## 배경

짧은 인물 질문, 예를 들어 `어우동이 누구야`, `정미수가 누구야`, `장녹수가 누구야` 같은 요청에서 내부 RAG가 근거를 못 찾으면 기존 Agent는 곧바로 조선왕조실록 검색을 호출했다. 문제는 검색어로 사용자 질문만 넘기는 것이 아니라 `사용자`, `현재 화면`, `사용자 질문`이 합쳐진 전체 컨텍스트 문자열을 그대로 넘기는 경우가 있었다는 점이다.

그 결과 실록 검색은 실제 키워드가 있어도 `no_results`가 되기 쉬웠고, 네이버/웹 검색 MCP tool을 추가한 뒤에도 Agent가 자동으로 사용하지 않았다.

## 수정 전 기준 로그

실행 조건:

- API: `/api/ai/agent/chat`
- 테스트 사용자로 로그인 후 호출
- OpenAI, Naver, Brave 키 없음
- 질문 세트:
  - `어우동이 누구야`
  - `정미수가 누구야`
  - `장녹수가 누구야`
  - `정조의 매운 편지 일부 찾아줘`

요약 결과:

| 질문 | RAG | 외부 검색 tool | 외부 검색 input | 외부 검색 상태 | 문제 |
| --- | --- | --- | --- | --- | --- |
| 어우동이 누구야 | 0건 | `history.search_sillok` | 전체 컨텍스트 문자열 | `no_results` | 검색어가 지저분하고 discovery 없음 |
| 정미수가 누구야 | 0건 | `history.search_sillok` | 전체 컨텍스트 문자열 | `no_results` | 동일 |
| 장녹수가 누구야 | 0건 | `history.search_sillok` | 전체 컨텍스트 문자열 | `no_results` | 동일 |
| 정조의 매운 편지 일부 찾아줘 | 3건 | `history.search_sillok` | 전체 컨텍스트 문자열 | `no_results` | 어찰/박물관/도서관 계열 discovery가 필요 |

핵심 판단:

- 내부 RAG 실패 이후 곧바로 실록만 검색하는 구조는 짧은 인물 질문에 약하다.
- 실록은 1차 discovery보다 2차 검증용에 가깝다.
- 네이버/웹 검색 tool이 있어도 Agent 흐름에 연결되지 않으면 사용자 체감은 바뀌지 않는다.

## 적용한 변경

`search_external`을 `history.external_evidence_bundle` 성격으로 바꿨다.

새 흐름:

```text
사용자 질문/컨텍스트
  -> 검색어 정제
  -> naver_search discovery
       - 기본 categories: encyc, webkr
       - 키 없으면 not_configured로 기록하고 계속 진행
  -> 네이버 결과 제목/설명/URL에서 실록 후보 키워드 추출
  -> sillok_search 검증
  -> web_search는 현재 비활성화
  -> 신뢰 도메인 우선 정렬
  -> Agent 최종 답변에 external_resources 반영
```

수정 파일:

- `backend/app/services/ai_runtime.py`
- `backend/app/services/editor_agent.py`
- `backend/app/api/ai.py`
- `backend/tests/test_auth_posts_comments.py`

## 수정 후 실제 로그

실행 조건은 수정 전과 동일하게 키 없이 실행했다.

| 질문 | RAG | 외부 검색 tool | 외부 검색 input | 외부 검색 상태 | 개선 |
| --- | --- | --- | --- | --- | --- |
| 어우동이 누구야 | 0건 | `history.external_evidence_bundle` | `어우동이 누구야` | `no_results` | 검색어 정제됨 |
| 정미수가 누구야 | 0건 | `history.external_evidence_bundle` | `정미수가 누구야` | `no_results` | 검색어 정제됨 |
| 장녹수가 누구야 | 0건 | `history.external_evidence_bundle` | `장녹수가 누구야` | `no_results` | 검색어 정제됨 |
| 정조의 매운 편지 일부 찾아줘 | 3건 | `history.external_evidence_bundle` | `정조의 매운 편지 일부 찾아줘` | `no_results` | 검색어 정제됨 |

중요한 한계:

- 현재 로컬/테스트 환경에는 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`이 없다.
- `BRAVE_SEARCH_API_KEY` 기반 web_search provider는 현재 기본 bundle에서 비활성화했다.
- 그래서 실제 네이버 discovery 결과 증가는 아직 확인할 수 없다.
- 이번 실제 로그에서 체감 개선은 “검색 입력 정제 + bundle 호출 경로 연결”까지다.

## 네이버 키 반영 후 재평가

실행 조건:

- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`을 Docker 백엔드 컨테이너에 반영
- `BRAVE_SEARCH_API_KEY` 기반 web_search는 기본 bundle에서 비활성화 유지
- API: `/api/ai/external/search`
- 입력은 UTF-8 JSON 요청으로 실행

키 반영 과정에서 확인한 문제:

- 사용자는 원본 worktree `C:\Dev\Crafton-Jungle\05.WebBoard\.env`에 키를 넣었다.
- 이 Codex 세션은 별도 worktree `C:\Users\이혜연\.codex\worktrees\a79e\05.WebBoard`에서 Docker Compose를 실행하고 있었다.
- 따라서 현재 실행 중인 Docker Compose가 읽는 `.env`에는 처음에 키가 없었다.
- `docker-compose.yml`도 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`을 컨테이너 environment로 넘기지 않고 있었다.

수정:

- `docker-compose.yml`의 `migrate`, `backend` 서비스에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `BRAVE_SEARCH_API_KEY` 전달을 추가했다.
- 원본 `.env`의 키를 현재 worktree `.env`로 복사했다. 값은 로그에 출력하지 않았다.
- 컨테이너 내부에서 `naver_client_id=True`, `naver_client_secret=True`를 boolean으로만 확인했다.

실제 결과:

| 질문 | 외부 검색 tool | 상태 | 결과 요약 |
| --- | --- | --- | --- |
| `어우동이 누구야` | `history.external_evidence_bundle` | `ok` | 네이버 백과 결과에서 `어우동` 항목들이 반환됨 |
| `장녹수가 누구야` | `history.external_evidence_bundle` | `ok` | 네이버 백과 결과에서 `장녹수` 항목들이 반환됨 |
| `정조 어찰` | `history.external_evidence_bundle` | 일부 실행 중 timeout 발생 | 네이버 직접 검색에서는 `정조 어찰첩`, `외가에 보낸 정조어찰...` 같은 후보가 확인됨 |

관찰:

- 네이버 키 반영 후 짧은 인물 질문은 더 이상 `no_results`에 머물지 않고 검색 후보를 반환한다.
- `어우동`, `장녹수`는 네이버 discovery만으로 후보 발견이 가능하다.
- `정조 어찰`은 검색 결과 후보는 있으나, 외부 호출 timeout이 발생할 수 있어 timeout/retry/caching 처리가 필요하다.

## 하드코딩 제거

초기 재평가 중 `어우동 -> 성종`, `장녹수 -> 연산군`처럼 특정 인물과 왕대를 직접 매핑하는 `DISCOVERY_CONTEXT_HINTS`를 잠깐 추가했다. 이 방식은 유지보수성과 확장성이 떨어지는 하드코딩이므로 제거했다.

현재 방식:

```text
어우동이 누구야
  -> 질문어 제거
  -> 조사 제거
  -> 어우동

장녹수가 누구야
  -> 질문어 제거
  -> 조사 제거
  -> 장녹수
```

즉, 특정 인물 지식 맵을 코드에 넣지 않고, 일반적인 질의 정제 규칙으로 네이버 discovery query를 만든다.

## 검색 품질 평가셋

새 평가셋은 후보 검색 품질과 답변 반영 품질을 분리해서 본다.

| ID | 질문 | 의도 | 기대 신호 |
| --- | --- | --- | --- |
| `person_eoudong` | `어우동이 누구야` | 짧은 인물 질문 | top3 제목에 `어우동` |
| `person_jangnoksu` | `장녹수가 누구야` | 짧은 인물 질문 | top3 제목에 `장녹수` |
| `person_hyoryeong` | `효령대군이 누구야` | 왕실 인물 질문 | top3 제목에 `효령대군` |
| `person_jeongmisu` | `정미수가 누구야` | 덜 알려진 인물 질문 | top3 제목에 `정미수` |
| `source_jeongjo_letters` | `정조 어찰` | 사료/문헌 후보 찾기 | top3 제목/설명에 `정조`, `어찰` |
| `source_hunminjeongeum` | `훈민정음 창제 근거` | 개념/사료 질문 | top3 제목에 `훈민정음` |
| `event_gyeyujeongnan` | `계유정난이 뭐야` | 사건 개괄 질문 | top3 제목에 `계유정난` |
| `culture_joseon_food` | `조선 왕실 음식` | 문화사 질문 | top3 제목에 `음식`, `수라`, `왕실` |

평가 기준:

- `status`: `ok` 또는 `cache_hit:ok`인지
- `title_hit_top3`: 기대 신호가 top3 제목에 있는지
- `trusted_top3`: top3 URL이 신뢰 가능한 도메인인지
- `elapsed_ms`: fresh 호출과 cache hit 호출 지연 시간
- 답변 반영: Agent 답변이 외부 후보 제목/provider를 언급하고, 확인 한계를 말하는지

## Timeout/Cache 개선

첫 평가에서 인물 질문 다수가 클라이언트 timeout에 걸렸다. 원인은 네이버 discovery 이후 실록 검증을 동기적으로 길게 기다리는 구조였다.

수정:

- `history.external_evidence_bundle` 결과를 Redis에 캐시한다.
- 캐시 hit는 `cache_hit:ok`처럼 표시한다.
- 네이버 discovery는 기본적으로 `encyc`를 먼저 호출하고, 결과가 없을 때만 `webkr`를 호출한다.
- 실록 검색 HTTP timeout을 3초로 줄였다.
- 네이버 검색 HTTP timeout을 4초로 줄였다.
- 짧은 인물 질문에서 네이버 top3 제목에 추출한 인물명이 있으면 실록 검증을 건너뛰고 빠르게 후보를 반환한다.

Fresh 재평가 결과:

| ID | 상태 | fresh latency | top3 hit | 비고 |
| --- | --- | ---: | --- | --- |
| `person_eoudong` | `ok` | 163ms | true | top3 모두 `어우동` |
| `person_jangnoksu` | `ok` | 88ms | true | top3에 `장녹수` |
| `person_hyoryeong` | `ok` | 85ms | true | top3에 `효령대군` |
| `person_jeongmisu` | `ok` | 84ms | true | top3에 `정미수` |
| `source_jeongjo_letters` | `ok` | 9102ms -> 정렬 개선 후 6168ms | true | `정조 어찰첩`이 1순위로 개선됨 |
| `source_hunminjeongeum` | `ok` | 9108ms | true | 실록 검증 대기 비용 큼 |
| `event_gyeyujeongnan` | `ok` | 101ms | true | top3 모두 `계유정난` |
| `culture_joseon_food` | `ok` | 3105ms | true | 첫 후보가 다소 부정확함 |

Cache 재평가 결과:

- 같은 평가셋을 두 번째 호출하면 대부분 2~26ms 수준으로 반환된다.
- 상태는 `cache_hit:ok`로 표시된다.

해석:

- 짧은 인물 질문 timeout 문제는 해결됐다.
- 사료/문헌형 질문은 여전히 실록 검증 때문에 6~9초대가 나올 수 있다.
- 이 유형은 실록 검증을 기본 동기 path에서 빼거나, partial result를 먼저 반환하는 방식이 필요하다.

## 답변 반영 평가

실행 조건:

- OpenAI 키 없음. 비용 없는 local fallback 기준.
- API: `/api/ai/agent/chat`
- 로그인 후 호출.

결과:

| 질문 | 결과 |
| --- | --- |
| `어우동이 누구야` | 답변이 `어우동` 네이버 후보를 근거 후보로 언급하고, 자료 확인 후 사실/해석을 분리하라고 안내 |
| `장녹수가 누구야` | 답변이 `장녹수` 관련 네이버 후보를 근거 후보로 언급 |
| `정조 어찰 자료 찾아줘` | 정렬 개선 전에는 `선조어서사...`가 우선 후보로 나오는 문제가 있었음 |

정렬 개선:

- 외부 후보 정렬에 질의어 적합성을 추가했다.
- 기존에는 신뢰도 위주라 `정조 어찰`에서 `선조어서사...`가 앞에 올 수 있었다.
- 개선 후 `정조 어찰 자료 찾아줘`의 1순위 후보가 `정조 어찰첩`으로 바뀌었다.

현재 local fallback 답변의 한계:

- 후보 제목과 provider는 말하지만, 후보 description을 요약해서 사실 답변까지 생성하지는 않는다.
- OpenAI 키가 없을 때는 “자료 후보를 찾았다” 수준의 안내에 머문다.
- 실제 서비스 품질을 높이려면 외부 후보 description을 짧게 요약하고, URL/provider/citation을 답변 구조에 포함해야 한다.

## Controlled 평가

네이버/실록 tool을 mock해서 provider가 결과를 반환하는 경우를 분리 검증했다.

확인한 내용:

- `history.naver_search`가 먼저 호출된다.
- 네이버 결과 설명에 `성종실록`, `연산군일기` 같은 신호가 있으면 실록 검색 후보를 만든다.
- 실록 기사 URL이 있으면 `sillok.history.go.kr/id/` 기사 링크를 우선순위 1순위로 올린다.
- 실록 검색 결과 페이지 URL은 근거로 쓰지 않도록 필터링한다.
- 외부 자료가 있으면 local fallback 답변도 더 이상 데모 문구만 내지 않고 외부 자료 후보를 언급한다.

추가된 테스트:

- `test_external_search_uses_naver_discovery_before_sillok`

검증 결과:

```text
30 passed
```

## 남은 작업

1. 네이버 API 호출 수를 로그에 더 명확히 남겨야 한다. 예: `naver.search · encyc/webkr · 2 calls · cached=false`
2. Redis 캐시는 bundle 단위로 적용됐지만, provider 단위 호출 수/캐시 여부도 별도 로그로 남겨야 한다.
3. `history.external_evidence_bundle`을 MCP tool로도 별도 노출하면 Agent 로그와 직접 디버깅이 더 쉬워진다.
4. 정조 어찰처럼 실록보다 박물관/도서관/한국학자료센터가 더 적합한 요청은 provider routing 규칙을 더 세분화해야 한다.
5. 범용 웹 검색이 필요해지면 Brave/Tavily/Google 계열 provider를 다시 활성화하되, 호출 비용과 신뢰 도메인 필터를 먼저 정해야 한다.
6. 사료/문헌형 질문은 6~9초대가 나올 수 있으므로 partial result 반환 또는 실록 검증 비동기화가 필요하다.
7. local fallback 답변은 후보 description 요약과 citation 표시가 부족하다.

## 결론

이번 변경으로 “tool은 있는데 Agent가 안 쓰는 상태”는 해소했다. 네이버 키 반영 후 `어우동`, `장녹수` 같은 짧은 인물 질문은 실제 네이버 후보를 반환하는 것을 확인했다.

현재 달라진 점은 명확하다.

- 수정 전: 전체 컨텍스트를 실록에 바로 던짐
- 수정 후: 질문을 정제하고, 네이버 discovery -> 실록 검증 순서로 검색하는 구조
- web_search/Brave는 현재 기본 bundle에서 비활성화

다음 품질 평가는 검색 후보를 실제 답변 생성에서 어떻게 인용/요약할지, 그리고 timeout/caching을 어떻게 처리할지에 집중해야 한다.
