# 외부 한국사 검색 Agent 트러블슈팅

작성일: 2026-06-17

## 목적

에디터 Agent가 사용자의 역사 질문에 답할 때, 내부 RAG에 근거가 없으면 외부 자료 provider를 검색한다.

그런데 실제 사용 중 다음 문제가 확인되었다.

```text
사용자 질문:
양녕대군이 고양이를 훔치려던 사건이 있다고 들었는데
인과관계를 자세히 서술해서 게시글 본문 채워줘

Agent 결과:
현재 확인 가능한 자료만으로는 사건의 세부를 단정하기 어렵습니다.
누구의 집이었는지, 실제로 데려갔는지 확인할 근거가 부족합니다.
```

사용자는 구글 검색에서는 바로 해당 사건이 보인다고 확인했다. 실제로 이 사건은 조선왕조실록의 다음 기사에 있다.

```text
태종실록 34권, 태종 17년 11월 24일 을해 2번째기사
세자가 금빛 고양이를 구하려 하다
https://sillok.history.go.kr/id/kca_11711024_002
```

따라서 이번 트러블슈팅의 목표는 단순히 특정 케이스 하나를 하드코딩하는 것이 아니라, 다음 검색 실패 패턴을 데이터 기반으로 줄이는 것이다.

- 사용자는 현대어, 별칭, 후대 표현으로 질문한다.
- 사료에는 당시 지위명, 인명, 한자명, 사건 단서로 기록된다.
- 검색어 하나를 그대로 외부 사이트에 던지면 관련 사료를 놓친다.
- 근거를 못 찾은 상태에서 Agent가 긴 해석문을 생성하면 사실 검증이 약해진다.

## 관련 코드

주요 변경 위치:

```text
backend/app/services/ai_runtime.py
backend/app/services/mcp_server.py
backend/app/services/editor_agent.py
backend/app/api/ai.py
backend/tests/test_auth_posts_comments.py
```

핵심 함수:

```text
search_external()
_external_query_candidates()
_search_external_candidates()
_external_resource_rank_key()
search_history_providers()
_search_sillok()
_parse_sillok_search_results()
```

## 기존 구조

처음 외부 검색은 사실상 검색 링크 생성에 가까웠다.

```text
사용자 keyword
→ 조선왕조실록 검색 URL 생성
→ 검색 링크를 ExternalResource로 반환
```

문제는 이 구조에서는 실제 검색 결과의 제목, 본문 excerpt, 기사 URL, 검증 상태를 가져오지 못한다는 점이다.

예전 동작은 다음에 가까웠다.

```json
{
  "title": "양녕대군 조선왕조실록 검색",
  "provider": "국사편찬위원회 조선왕조실록",
  "url": "https://sillok.history.go.kr/search/searchResultList.do?keyword=...",
  "verification_status": ""
}
```

이 상태에서는 Agent가 다음을 판단할 수 없다.

- 검색 결과가 실제 기사인지
- 검색 링크만 있는 것인지
- 1차 사료인지
- 본문에 사용자가 묻는 사건 단서가 있는지
- citation으로 써도 되는지

## 증상 1: 양녕대군 고양이 사건을 못 찾음

### 사용자 관찰

구글에서 `양녕대군 고양이 사건`으로 검색하면 다음 정보가 나온다.

```text
양녕대군이 신효창의 집에 있던 금빛 고양이를 구하려 했다.
태종실록에 기록되어 있다.
```

하지만 우리 Agent는 다음처럼 답했다.

```text
현재 확인 가능한 자료만으로는 이 일화의 세부를 단정하기 어렵습니다.
누구의 집이었는지, 고양이를 실제로 데려갔는지 확인할 근거가 부족합니다.
```

### 원인 가설

처음에는 "MCP provider가 부족해서 그런가?"라고 볼 수 있었다. 그러나 실제 원인은 provider 개수보다 다음에 가까웠다.

```text
검색어 생성 능력 부족
+ 실록 검색 URL/HTML 파서 불일치
+ 검색 결과 재랭킹 부족
```

즉, provider를 많이 붙여도 다음 단계를 못 하면 실패한다.

```text
사용자 질문
→ 핵심 인물/사건/단서 추출
→ 검색어 후보 여러 개 생성
→ 실록 검색 실행
→ 결과 title뿐 아니라 snippet/detail 본문 파싱
→ 신효창 같은 새 단서 활용
→ 최종 실록 기사 URL과 본문 근거를 citation으로 사용
```

## 증상 2: 문종 첫 번째 부인 이슈도 처음에는 잘못 찾음

양녕대군 케이스만 고치면 특정 사건 패치가 된다. 그래서 다른 형태의 질문도 확인했다.

```text
문종의 첫번째 부인 이슈
```

이 질문은 사용자가 `문종`, `첫번째 부인`, `이슈`라는 현대식 표현으로 묻는다. 실록에서는 핵심 단서가 다음처럼 나온다.

```text
휘빈 김씨
세자빈 김씨
폐빈
폐출
압승술
세종실록 45권, 세종 11년 7월 20일 갑자 3번째기사
https://sillok.history.go.kr/id/kda_11107020_003
```

초기 검색에서는 `문종 세자빈`처럼 너무 넓은 후보가 상위에 올라왔다.

실패 예:

```text
1순위:
성종실록 29권, 성종 4년 4월 28일
대왕 대비가 원상들과 정미수를 처리하는 문제를 논의하다

excerpt:
... 문종은 이미 종묘에 부묘하였으므로 ...
... 세자빈과 동성 ...
```

이 결과는 `문종`과 `세자빈`이라는 단어는 포함하지만, 사용자가 물은 첫 번째 부인 이슈와 직접 관련된 기사가 아니다.

## 측정 기준

이번 수정은 감으로 판단하지 않고 다음 기준으로 확인했다.

| 기준 | 의미 |
| --- | --- |
| top1 URL | 첫 번째 결과가 실제 관련 실록 기사인지 |
| verification_status | `primary_verified`인지 |
| content_excerpt | 본문에 사건 핵심 단서가 포함되는지 |
| tool_log.input | 어떤 검색 후보가 실제로 사용되었는지 |
| elapsed_ms | 사용자 체감 가능한 시간인지 |
| pytest | 회귀 테스트 통과 여부 |

## 1단계: 실록 검색 URL 확인

기존 실록 검색 URL은 현재 사이트 구조와 맞지 않았다.

기존:

```text
https://sillok.history.go.kr/search/searchResultList.do?keyword={keyword}
```

수정:

```text
https://sillok.history.go.kr/search/searchResultList.do?topSearchWord={keyword}&pageUnit=10
```

이 변경 후 실록 검색 결과 페이지에서 실제 결과 박스를 파싱할 수 있었다.

## 2단계: 실록 HTML 파서 수정

현재 실록 검색 결과 HTML은 대략 다음 구조를 가진다.

```html
<div class="result-box">
  <a href="javascript:goView('kca_11711024_002', 1);" class="subject">
    태종실록 34권 ...
  </a>
  <p class="text">
    세자(世子)가 금빛 고양이를 신효창(申孝昌)의 집에 구하니...
  </p>
</div>
```

그래서 파서를 다음 기준으로 수정했다.

```text
result-box 단위로 검색 결과 분리
→ goView('ARTICLE_ID')에서 기사 ID 추출
→ subject에서 제목 추출
→ p.text에서 본문 excerpt 추출
→ https://sillok.history.go.kr/id/{ARTICLE_ID} URL 생성
```

검증 결과:

```json
{
  "title": "1. 태종실록 34권, 태종 17년 11월 24일 을해 2번째기사 / 세자가 금빛 고양이를 구하려 하다",
  "url": "https://sillok.history.go.kr/id/kca_11711024_002",
  "verification_status": "primary_verified",
  "content_excerpt": "세자(世子)가 금빛 고양이를 신효창(申孝昌)의 집에 구하니..."
}
```

## 3단계: 단일 검색어에서 검색 후보 목록으로 변경

단일 검색어:

```text
양녕대군 고양이 사건
```

이것만으로는 충분하지 않다. 실록에는 `양녕대군` 대신 `세자`, 사건 단서로 `신효창`, `금빛 고양이`, 한자 원문에는 `猫`가 나온다.

그래서 검색 후보를 여러 개 생성하도록 바꿨다.

양녕대군 고양이 케이스 후보:

```text
양녕대군 고양이 사건
양녕대군 고양이
신효창 고양이
태종실록 신효창 고양이
申孝昌 猫
```

문종 첫 부인 케이스 후보:

```text
문종의 첫번째 부인 이슈
문종 첫번째 부인 이슈
문종 첫번째
문종 세자빈
휘빈 김씨
세자빈 김씨 폐출
세자빈 김씨 압승
世子嬪 金氏
```

LLM API 키가 있으면 `_external_query_candidates()`가 query planner prompt로 후보를 만든다.

키가 없거나 LLM 호출이 실패하면 local fallback 후보를 쓴다.

중요한 점은 fallback은 최종 답변용이 아니라 검색 안정성을 위한 안전장치라는 것이다.

## 4단계: provider 실행 순서 조정

처음에는 각 후보마다 provider 전체를 돌렸다.

```text
후보 8개
× auto provider 전체
= 실록, 백과, 박물관, 도서관, 고문서, 웹 반복 호출
```

이 방식은 정확도를 높일 수는 있지만 실제 응답 시간이 너무 길어졌다.

실측:

| 단계 | 양녕대군 고양이 사건 elapsed_ms | 결과 |
| --- | ---: | --- |
| 후보마다 auto provider 전체 호출 | 120초 초과 | timeout |
| 실록 + 보조 provider + 단서 재검색 | 약 82041ms | 성공하지만 너무 느림 |
| 1차 사료 발견 후 단서 재검색 생략 | 약 42437ms | 성공하지만 아직 느림 |
| 실록 우선, 1차 사료 발견 시 즉시 반환 | 약 2622ms | 성공 |
| 생애형 질문은 1차 사료 발견 후에도 단서 기반 2차 검색 | 약 11654ms | 여러 생애 슬롯 확보 |

최종 전략:

```text
모든 후보에 대해 sillok 먼저 검색
→ 일반 lookup/event 질문은 primary_verified가 있으면 즉시 재랭킹 후 반환
→ biography 질문은 primary_verified가 있어도 결과에서 단서를 뽑아 2차 검색
→ 1차 사료가 없을 때는 보조 provider 검색
```

보조 provider:

```text
어찰/편지/서찰/고문서/문집/원문:
  kostma, nlk, encykorea, web

복식/유물/소장품/그림/초상/어진/이미지:
  museum, encykorea, web

일반:
  encykorea, museum, web
```

이렇게 바꾼 이유:

- 실록 1차 사료가 있으면 그것이 가장 강한 근거다.
- 이미 1차 사료를 찾았는데 박물관/웹 검색 링크를 더 붙이는 것은 정확도보다 지연을 크게 늘린다.
- 보조 provider는 1차 사료가 없을 때 참고 자료를 찾는 용도로 쓰는 것이 낫다.

## 5단계: 재랭킹 실패 수정

문종 첫 부인 케이스에서 중요한 문제가 있었다.

`세자빈 김씨 폐출` 후보는 정확한 기사를 찾았지만, 최종 정렬에서는 `문종 세자빈`의 일반 결과가 위로 올라왔다.

실제 디버그 출력:

```text
candidates:
문종의 첫번째 부인 이슈
문종 첫번째 부인 이슈
문종 첫번째
문종 세자빈
휘빈 김씨
세자빈 김씨 폐출
세자빈 김씨 압승
世子嬪 金氏
```

문제 결과:

```text
(planner_ratio=1.0, primary=1.0, original_ratio=0.25, score=3.55)
planner_query=문종 세자빈
title=성종실록 29권 ... 정미수를 처리하는 문제

(planner_ratio=1.0, primary=1.0, original_ratio=0.0, score=3.32)
planner_query=세자빈 김씨 폐출
title=세종실록 45권 ... 휘빈 김씨의 폐빈
```

왜 틀렸나:

- `문종 세자빈` 결과는 본문에 `문종`과 `세자빈`이 모두 있어서 원 질문 단어 매칭 점수가 높았다.
- 그러나 실제 핵심 사건은 문종이 왕이 되기 전 세자 시절의 일이라, 정확한 기사 제목에는 `문종`이 나오지 않는다.
- 즉, 원 질문 단어가 많이 들어간 결과가 항상 더 정확하지 않다.

수정:

```text
원 질문 매칭보다
구체화된 검색 후보가 결과 본문에 얼마나 잘 맞는지를 더 우선한다.
```

랭킹 키:

```text
planner_ratio
specificity
primary
original_ratio
score
```

의미:

| 항목 | 설명 |
| --- | --- |
| planner_ratio | 검색 후보의 단어들이 결과 title/excerpt에 얼마나 포함되는지 |
| specificity | 후보가 얼마나 구체적인지. 예: `세자빈 김씨 폐출`이 `문종 세자빈`보다 구체적 |
| primary | 1차 사료인지 |
| original_ratio | 원 질문 단어와의 매칭 |
| score | provider 내부 relevance score와 보정 점수 |

수정 후 디버그 출력:

```text
(1.0, 0.6, 1.0, 0.0, 3.32)
planner_query=세자빈 김씨 폐출
title=세종실록 45권 ... 휘빈 김씨의 폐빈
url=https://sillok.history.go.kr/id/kda_11107020_003

(1.0, 0.4, 1.0, 0.25, 3.55)
planner_query=문종 세자빈
title=성종실록 29권 ... 정미수를 처리하는 문제
```

구체 후보의 `specificity=0.6`이 넓은 후보의 `specificity=0.4`보다 높아서 정확한 기사가 위로 올라왔다.

## 최종 검증 결과

### 케이스 1: 양녕대군 고양이 사건

실행:

```powershell
python -c "from app.services.ai_runtime import search_external; from app.core.config import Settings; import json;
class DB:
 def add(self,*a,**k): pass
 def commit(self): pass
r=search_external(DB(), '양녕대군 고양이 사건', Settings(openai_api_key=None)); print('tool', r.tool_log.input, r.tool_log.status, r.tool_log.elapsed_ms); print(json.dumps([{'title':x.title,'url':x.url,'status':x.verification_status,'excerpt':(x.content_excerpt or '')[:160]} for x in r.resources[:3]], ensure_ascii=False, indent=2))"
```

결과:

```text
tool:
양녕대군 고양이 사건 | 양녕대군 고양이 | 신효창 고양이 | 태종실록 신효창 고양이 | 申孝昌 猫

status:
ok

elapsed_ms:
2622
```

1순위 결과:

```json
{
  "title": "1. 태종실록 34권, 태종 17년 11월 24일 을해 2번째기사 / 세자가 금빛 고양이를 구하려 하다",
  "url": "https://sillok.history.go.kr/id/kca_11711024_002",
  "status": "primary_verified",
  "excerpt": "세자(世子)가 금빛 고양이를 신효창(申孝昌)의 집에 구하니..."
}
```

이제 Agent는 최소한 다음 사실을 근거 기반으로 쓸 수 있다.

```text
누구의 고양이인가:
신효창의 집에 있던 금빛 고양이

사건 흐름:
세자가 신효창의 집에 금빛 고양이를 구했다.
신효창은 따르지 않고 빈객 탁신에게 고했다.
탁신이 서연관을 불렀고, 서연관이 세자에게 부적절함을 아뢰었다.
세자는 금빛 수고양이가 드물다고 하여 보고 돌려보내려 했다고 말했다.
```

### 케이스 2: 문종의 첫번째 부인 이슈

실행:

```powershell
python -c "from app.services.ai_runtime import search_external; from app.core.config import Settings; import json;
class DB:
 def add(self,*a,**k): pass
 def commit(self): pass
r=search_external(DB(), '문종의 첫번째 부인 이슈', Settings(openai_api_key=None)); print('tool', r.tool_log.input, r.tool_log.status, r.tool_log.elapsed_ms); print(json.dumps([{'title':x.title,'url':x.url,'status':x.verification_status,'excerpt':(x.content_excerpt or '')[:180]} for x in r.resources[:5]], ensure_ascii=False, indent=2))"
```

결과:

```text
tool:
문종의 첫번째 부인 이슈 | 문종 첫번째 부인 이슈 | 문종 첫번째 | 문종 세자빈 | 휘빈 김씨 | 세자빈 김씨 폐출

status:
ok

elapsed_ms:
3440
```

1순위 결과:

```json
{
  "title": "1. 세종실록 45권, 세종 11년 7월 20일 갑자 3번째기사 / 근정전에서 임금이 휘빈 김씨의 폐빈에 대해 하교하다",
  "url": "https://sillok.history.go.kr/id/kda_11107020_003",
  "status": "primary_verified",
  "excerpt": "책봉하고, 김씨를 누대(累代) 명가(名家)의 딸이라고 하여 간택(揀擇)하여서 세자빈(世子 嬪)을 삼았더니, 뜻밖에도 김씨가 미혹(媚惑)시키는 방법으로써 압승술(壓勝術)을 쓴 단서가 발각되었다..."
}
```

이제 Agent는 다음 사실을 근거 기반으로 쓸 수 있다.

```text
문종의 첫 번째 세자빈은 휘빈 김씨다.
세종 11년 7월 20일 기사에서 휘빈 김씨의 폐빈 문제가 다뤄진다.
핵심 사유는 압승술 관련 단서가 발각되었다는 실록 기록이다.
```

### 케이스 3: 경혜공주의 생애

#### 초기 실패

사용자 질문:

```text
경혜공주의 생애
```

초기 실행 결과:

```text
tool:
경혜공주의 생애 | 경혜공주 생애

status:
link_ready

elapsed_ms:
4546
```

반환된 자료는 `primary_verified` 실록 기사가 아니라 검색 링크뿐이었다.

```json
[
  {
    "title": "경혜공주 생애 국립중앙박물관 소장품 검색",
    "status": "unverified",
    "excerpt": ""
  },
  {
    "title": "경혜공주 생애 화이트리스트 웹 검색",
    "status": "unverified",
    "excerpt": ""
  }
]
```

그런데 `경혜공주` 단독으로 검색하면 실록 결과가 바로 나왔다.

```json
[
  {
    "title": "문종실록 7권, 문종 1년 4월 1일 / 윤면이 경혜 공주의 집을 짓는 데 30여 가의 인가가 철거됨을 아뢰다",
    "url": "https://sillok.history.go.kr/id/kea_10104001_006",
    "verification_status": "primary_verified"
  },
  {
    "title": "문종실록 13권, 문종 2년 9월 1일 / 문종 대왕 묘지문",
    "url": "https://sillok.history.go.kr/id/kea_10209001_003",
    "verification_status": "primary_verified"
  }
]
```

#### 실패 원인

`경혜공주의 생애`는 사용자 입장에서는 자연스러운 질문이지만, 실록 검색어로는 불리했다.

```text
경혜공주의
→ 조사 "의"가 붙어 핵심 인물명 "경혜공주"와 다르게 검색됨

생애
→ 실록 기사 제목/본문에 자주 등장하는 단어가 아님
```

따라서 실제 검색에 필요한 후보는 다음에 가까웠다.

```text
경혜공주
경혜공주 묘지문
경혜공주 하가
경혜공주 부의
경혜공주 아들
```

#### 1차 수정: 조사 처리

기존 `_query_keywords()`는 모든 `의` 글자를 공백으로 바꾸고 있었다.

이 방식은 `경혜공주의`를 `경혜공주`로 만드는 데는 도움이 되지만, 다른 정상 단어를 깨뜨릴 수 있다.

```text
임진왜란 의병 활동
→ 임진왜란 병 활동
```

그래서 다음처럼 바꿨다.

```text
모든 "의" 제거
→ 토큰 끝에 붙은 조사 "의"만 제거
```

검증:

```py
_query_keywords("경혜공주의 생애")
# ["경혜공주", "생애"]

_query_keywords("임진왜란 의병 활동")
# ["임진왜란", "의병", "활동"]
```

#### 2차 수정: 핵심 인물 단독 후보 추가

기존 후보:

```text
경혜공주의 생애
경혜공주 생애
```

수정 후 후보:

```text
경혜공주의 생애
경혜공주
경혜공주 생애
```

이 변경만으로도 실록 1차 사료를 찾을 수 있었다.

실측:

```text
tool:
경혜공주의 생애 | 경혜공주 | 경혜공주 생애

status:
ok

elapsed_ms:
658
```

하지만 이 결과는 생애 질문의 전체 맥락에는 부족했다. 집 건축 사건은 경혜공주 생애의 한 장면일 뿐, 가족관계·혼인·단종과의 관계·남편 정종의 죽음·아들 정미수·사망 정황까지 충분히 보여주지 못했다.

#### 3차 수정: 생애형 질문 후보 확장

생애형 질문에서는 인물의 전 생애를 구성할 수 있는 자료가 필요하다.

경혜공주 케이스에서 유효했던 후보:

```text
경혜공주 묘지문
경혜공주 하가
경혜공주 부의
경혜공주 아들
```

후보별 실험 결과:

| 후보 | 찾은 핵심 자료 | 의미 |
| --- | --- | --- |
| `경혜공주 묘지문` | 문종 대왕 묘지문 | 문종의 딸, 단종의 누이, 정종에게 하가 |
| `경혜공주 하가` | 예종실록 재산 반환 기사 | 정종에게 하가, 정종 주살, 재산 적몰, 세조의 반환 |
| `경혜공주 부의` | 성종실록 부의 기사 | 사망, 부의, 정종 주살 뒤 여승이 됨, 가난 |
| `경혜공주 아들` | 예종실록/성종실록 정미수 기사 | 아들 정미수의 신분·서용 문제 |

이 단계까지는 여전히 사후적 성격이 남아 있었다.

```text
경혜공주 실패
→ 공주/옹주 생애 후보를 보강
```

이 방식은 특정 인물 하드코딩은 아니지만, 사용자가 지적한 대로 여전히 "실패한 뒤 후보를 추가"하는 패턴이다.

#### 4차 수정: 결과 기반 deep retrieval

더 나은 방식은 처음부터 모든 후보를 사람이 아는 것이 아니라, 1차 검색 결과에서 새 단서를 뽑아 2차 검색을 수행하는 것이다.

예:

```text
1차 검색:
경혜공주

1차 결과 excerpt:
딸은 경혜 공주(敬惠公主)로 책봉되어 영양위(寧陽尉) 정종(鄭悰)에게 하가(下嫁)했습니다.

추출 단서:
영양위
정종
하가

2차 검색:
경혜공주 영양위
경혜공주 정종
경혜공주 하가
```

또 다른 결과:

```text
excerpt:
정종이 주살되니 공주는 머리를 깎고 여승이 되었고, 아들 정미수(鄭眉壽)는 나이 16세였다.

추출 단서:
정미수
부의
주살
여승

2차 검색:
경혜공주 정미수
경혜공주 부의
경혜공주 주살
경혜공주 여승
```

구현 원칙:

```text
1차 사료가 있어도 biography 질문이면 즉시 종료하지 않는다.
검색 결과 title/description/content_excerpt에서 인물명, 관직, 관계어, 사건어를 추출한다.
단서 단독 검색보다 "{subject} {clue}" 형태를 우선한다.
템플릿 후보보다 실제 결과에서 발견한 단서를 우선한다.
```

단서 추출 예:

```py
_external_clue_queries("경혜공주의 생애", resources)
```

결과:

```text
경혜공주 영양위
경혜공주 정종
경혜공주 하가
경혜공주 정미수
경혜공주 부의
경혜공주 주살
```

이제 생애형 질문의 일반 후보는 다음처럼 동작한다.

```text
질문에 생애/일생/삶/인생이 있고
→ 핵심 인물 단독 검색
→ 일반 생애 probe 검색
→ 결과에서 새 단서 추출
→ subject + clue 형태로 2차 검색
```

초기 후보:

```text
경혜공주의 생애
경혜공주
경혜공주 생애
경혜공주 묘지문
경혜공주 하가
경혜공주 부의
경혜공주 아들
```

2차 후보:

```text
경혜공주 영양위
경혜공주 정종
경혜공주 하가
경혜공주 정미수
경혜공주 부의
경혜공주 주살
```

#### 최종 검증

실행:

```powershell
python -c "from app.services.ai_runtime import search_external; from app.core.config import Settings; import json;
class DB:
 def add(self,*a,**k): pass
 def commit(self): pass
r=search_external(DB(), '경혜공주의 생애', Settings(openai_api_key=None)); print('tool', r.tool_log.input, r.tool_log.status, r.tool_log.elapsed_ms); print(json.dumps([{'title':x.title,'url':x.url,'status':x.verification_status,'excerpt':(x.content_excerpt or '')[:240]} for x in r.resources[:10]], ensure_ascii=False, indent=2))"
```

결과:

```text
tool:
경혜공주의 생애 | 경혜공주 | 경혜공주 생애 | 경혜공주 묘지문 | 경혜공주 하가 | 경혜공주 부의

status:
ok

elapsed_ms:
11654
```

상위 결과:

```json
[
  {
    "title": "문종실록 13권, 문종 2년 9월 1일 / 문종 대왕 묘지문",
    "url": "https://sillok.history.go.kr/id/kea_10209001_003",
    "status": "primary_verified",
    "excerpt": "딸은 경혜 공주로 책봉되어 영양위 정종에게 하가했습니다..."
  },
  {
    "title": "예종실록 5권, 예종 1년 4월 10일 / 명하여 경혜 공주에게 황금 2정과 백금 6정을 돌려주게 하다",
    "url": "https://sillok.history.go.kr/id/kha_10104010_002",
    "status": "primary_verified",
    "excerpt": "공주는 문종의 딸로 영양위 정종에게 하가하였는데, 정종이 주살됨으로 가재가 모두 적몰되었다..."
  },
  {
    "title": "성종실록 38권, 성종 5년 1월 1일 / 호조에 명하여 경혜 공주에게 부의로 재물을 내리도록 하다",
    "url": "https://sillok.history.go.kr/id/kia_10501001_004",
    "status": "primary_verified",
    "excerpt": "정종이 주살되니 공주는 머리를 깎고 여승이 되었는데, 매우 가난하였으므로..."
  },
  {
    "title": "성종실록 30권, 성종 4년 5월 1일 / 충훈부에서 정미수에게 관직을 제수하는 것이 옳지 않다고 아뢰다",
    "url": "https://sillok.history.go.kr/id/kia_10405001_003",
    "status": "primary_verified",
    "excerpt": "정미수는 정종의 아들. 어머니는 문종의 딸 경혜 공주..."
  },
  {
    "title": "단종실록 12권, 단종 2년 8월 5일 / 영양위 정종·윤사로 등에게 노비를 내려 주다",
    "url": "https://sillok.history.go.kr/id/kfa_10208005_002",
    "status": "primary_verified",
    "excerpt": "정종은 문종의 부마, 문종 제1녀 경혜 공주의 남편..."
  }
]
```

이제 Agent는 `경혜공주의 생애`에 대해 다음 축으로 본문을 구성할 수 있다.

```text
출신:
문종의 딸, 단종의 누이

혼인:
영양위 정종에게 하가

정치적 비극:
정종이 주살되고 가재가 적몰됨

후반 생애:
머리를 깎고 여승이 되었으며 가난했다는 사신의 논평

자녀:
아들 정미수의 서용·관직 문제가 후대 실록에 반복 등장

사망:
성종 5년 정월 부의 기사로 사망 정황 확인
```

#### 회귀 테스트

추가 테스트:

```text
test_external_query_candidates_expand_princess_lifecycle_terms
test_external_search_finds_princess_lifecycle_sources
test_external_clue_queries_expand_followup_terms_from_search_results
```

검증 내용:

```text
경혜공주의 생애 → 경혜공주, 경혜공주 묘지문, 경혜공주 하가, 경혜공주 부의, 경혜공주 아들 후보 생성
임진왜란 의병 활동 → 의병 단어가 조사 제거 로직 때문에 깨지지 않음
생애형 후보로 정종/정미수 관련 primary_verified 자료가 반환됨
검색 결과 excerpt에서 정종/정미수/부의/주살 단서를 추출해 subject+clue 후속 검색어를 생성함
```

테스트 결과:

```text
python -m pytest tests/test_auth_posts_comments.py -q

24 passed, 56 warnings
```

## 회귀 테스트

실행 위치:

```text
C:\Dev\Crafton-Jungle\05.WebBoard\backend
```

명령:

```powershell
python -m pytest tests/test_auth_posts_comments.py -q
```

결과:

```text
24 passed, 56 warnings
```

추가된 테스트 의도:

| 테스트 | 검증 내용 |
| --- | --- |
| `test_editor_agent_preserves_event_terms_for_yangnyeong_cat_search` | 에디터 Agent가 `고양이` 같은 사건 단서를 검색어에 보존하는지 |
| `test_history_search_expands_and_reranks_yangnyeong_cat_queries` | `신효창`, `태종실록 신효창 고양이` 후보가 생성되고 1차 사료가 상위에 오는지 |
| `test_editor_agent_holds_specific_story_draft_without_primary_source` | 1차 사료 없이 구체 사건을 긴 본문으로 단정 생성하지 않는지 |
| `test_external_search_uses_llm_query_planner_candidates` | LLM query planner가 만든 `휘빈 김씨` 후보를 실제 검색에 사용하는지 |
| `test_external_query_candidates_expand_princess_lifecycle_terms` | 생애형 질문에서 핵심 인물명과 생애 probe 후보를 생성하는지 |
| `test_external_search_finds_princess_lifecycle_sources` | 경혜공주 생애 검색에서 정종/정미수 관련 1차 사료를 찾는지 |
| `test_external_clue_queries_expand_followup_terms_from_search_results` | 검색 결과 excerpt에서 새 단서를 추출해 후속 검색어를 만드는지 |

## 최종 동작 흐름

```text
사용자 질문
→ safety/domain check
→ 에디터 Agent가 외부 검색 keyword 생성
→ search_external()
→ _external_query_candidates()
   - OpenAI key 있음: LLM query planner 사용
   - OpenAI key 없음: local fallback 사용
→ _search_external_candidates()
   - 모든 후보에 대해 sillok 먼저 검색
   - 일반 lookup/event 질문은 primary_verified가 있으면 즉시 반환
   - biography 질문은 primary_verified가 있어도 deep retrieval 계속 수행
   - 1차 사료가 없으면 보조 provider 검색
→ _external_clue_queries()
   - title/description/content_excerpt에서 인물명, 관직, 사건어 추출
   - 단서 단독보다 "{subject} {clue}" 후속 검색어 생성
→ 2차 _search_external_candidates()
   - 단서 기반 후속 검색으로 누락된 생애 슬롯 보강
→ _rank_external_raw_resources()
   - primary
   - verified
   - planner_ratio
   - specificity
   - original_ratio
   - score
→ Agent가 citation 가능한 근거로 본문 생성
```

## 이번 사례에서 얻은 원칙

### 1. provider 개수를 늘리는 것만으로는 해결되지 않는다

처음에는 `한국민족문화대백과`, `국립중앙박물관`, `한국학자료센터`, `국립중앙도서관`, `웹 검색`을 더 붙이면 해결될 것처럼 보였다.

하지만 실제 실패 원인은 provider 부족보다 다음에 있었다.

```text
검색어를 어떻게 바꿔 던질 것인가
검색 결과 본문을 실제로 파싱하는가
어떤 결과를 1순위로 볼 것인가
1차 사료와 2차 자료를 구분하는가
```

### 2. 구글 같은 검색은 LLM만으로 되는 것이 아니다

구글은 사용자가 입력한 단어만 보는 것이 아니라 다음을 한다.

```text
색인
동의어
엔티티
문서 랭킹
클릭/품질 신호
본문 snippet
권위 있는 출처 우선순위
```

우리 프로젝트에서는 그중 최소한 다음을 구현했다.

```text
검색어 후보 확장
실제 결과 파싱
출처 유형 구분
1차 사료 우선
구체 후보 재랭킹
실패 시 단정 생성 억제
```

### 3. 원 질문 단어 매칭만으로 랭킹하면 틀릴 수 있다

문종 첫 부인 케이스가 대표적이다.

정확한 실록 기사는 문종이 왕이 되기 전 세자 시절의 사건이라 제목에 `문종`이 나오지 않는다.

따라서 다음 결과가 더 정확하다.

```text
세자빈 김씨 폐출
휘빈 김씨
압승술
```

단순히 `문종`이 많이 나오는 결과보다, query planner가 만든 구체 후보와 잘 맞는 결과를 더 신뢰해야 한다.

### 4. 1차 사료를 찾았으면 보조 provider를 계속 돌리지 않는다

중간 측정에서 82초, 42초가 걸렸던 이유는 이미 실록 기사를 찾고도 박물관/웹/도서관/고문서 검색을 계속했기 때문이다.

최종적으로는 다음 정책이 더 좋았다.

```text
일반 질문에서 1차 사료 있음:
  즉시 반환

생애형 질문에서 1차 사료 있음:
  인물/관직/가족관계/사건어 단서를 추출해 2차 검색

1차 사료 없음:
  백과/박물관/도서관/고문서/웹으로 보조 검색
```

이 정책으로 양녕대군 케이스는 약 2.6초, 문종 케이스는 약 3.4초가 되었다.

## 남은 한계

이번 수정은 검색 Agent의 구조를 개선했지만, 완전한 검색 엔진은 아니다.

남은 과제:

- 실록 검색 결과를 매번 외부 사이트에 요청하므로 네트워크 상태에 영향을 받는다.
- LLM query planner는 API 키가 있을 때만 작동한다.
- LLM query planner 호출은 토큰 비용이 발생할 수 있으므로 캐시가 중요하다.
- local fallback은 일부 대표 패턴만 보강한다.
- 평민 생활사, 제도사, 지역사처럼 왕실 사건이 아닌 질문은 별도 평가셋이 더 필요하다.
- 보조 provider의 실제 상세 본문 파싱 품질은 provider별로 계속 개선해야 한다.
- 실록 검색 결과가 한문/국역 중복으로 함께 반환될 수 있다.

## 다음 개선 제안

### 평가셋 추가

검색 품질은 대표 질문 세트로 계속 측정해야 한다.

예:

```text
양녕대군 고양이 사건
문종 첫 번째 부인 휘빈 김씨 폐출
정조의 매운 편지
광해군 재평가
세종대 훈민정음 창제 반대
조선시대 평민의 혼인 생활
조선 후기 장시와 보부상
임진왜란 의병 활동
```

각 질문마다 기대값을 둔다.

```text
expected_top_url
expected_terms
expected_source_type
max_elapsed_ms
```

### 검색 로그 저장

운영 중에는 다음을 DB나 로그에 남기면 좋다.

```text
original_query
query_candidates
provider_names
top_urls
top_titles
verification_status
elapsed_ms
user_selected_or_rejected
```

이 데이터가 쌓이면 다음을 판단할 수 있다.

- 어떤 질문군에서 실패가 잦은지
- 어떤 provider가 느린지
- LLM planner가 만든 후보가 실제로 도움이 되는지
- 특정 후보가 오히려 noise를 만드는지

### 색인 기반 보강

외부 사이트를 매번 검색하기보다 자주 쓰는 사료는 내부 색인으로 가져오는 것이 장기적으로 안정적이다.

추천 구조:

```text
외부 사료 수집
→ 원문/국역/메타데이터 보관
→ 검색용 정규화
→ BM25 또는 full-text index
→ embedding index
→ Agent planner가 corpus 선택
```

이렇게 되면 구글처럼 빠르고 안정적인 검색에 가까워진다.
