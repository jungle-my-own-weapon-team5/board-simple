# FitLog 발표 자료 정리

## 1. 프로젝트 주제

FitLog는 기존 게시판 서비스에 추가된 식단 관리 기능입니다.

사용자는 하루 식단을 기록하고, 서비스는 기록된 음식 정보를 바탕으로 하루 영양 상태를 계산합니다. 이후 RAG, AI Agent, MCP를 이용해 개인화된 식단 전략을 생성하고 외부 AI 도구와도 연결할 수 있는 구조를 구현했습니다.

핵심 주제는 다음과 같습니다.

> 사용자의 식단 기록을 기반으로 하루 영양 리포트를 만들고, RAG 기반 Diet Strategy Agent가 개인화된 식단 전략을 생성하는 서비스

## 2. 현재 구현된 기능

현재 구현된 주요 기능은 다음과 같습니다.

- 로그인 사용자 전용 FitLog 영역
- 목표 체중, 목표 날짜, 하루 목표 칼로리 설정
- 아침, 점심, 저녁, 간식 식단 기록
- 아침/점심/저녁은 날짜별 1개만 유지
- 간식은 여러 개 등록 가능
- 음식명과 분량 기반 영양성분 추정
- 추정된 영양성분 DB 캐시
- 하루 식단 리포트 생성
- 전략 생성 및 전략 기록 저장
- 우측 하단 Coach 패널
- MCP 서버를 통한 외부 AI 도구 연결
- ResNet-34 기반 이미지 음식 분류 실험 기능

## 3. 전체 서비스 흐름

FitLog의 기본 흐름은 다음과 같습니다.

```text
사용자 로그인
→ FitLog 목표 설정
→ 식단 기록 추가
→ 음식명/분량 또는 이미지 분석으로 음식 후보 생성
→ 영양성분 계산
→ 하루 리포트 생성
→ RAG로 관련 영양 지식 검색
→ AI Agent가 식단 전략 생성
→ 전략 기록 저장
```

## 4. 식단 기록 기능

식단 기록은 `POST /api/fitlog/meals` API로 처리됩니다.

관련 코드:

- `backend/app/api/fitlog.py`
- `backend/app/services/fitlog.py`
- `backend/app/models/fitlog.py`
- `frontend/src/screens/FitlogMealFormPage.tsx`

구현된 동작:

- 날짜, 식사 타입, 시간, 메모, 음식 목록, 이미지를 입력받음
- 이미지 원본과 crop 이미지를 파일로 저장
- 음식명과 분량만 입력해도 서버가 영양성분을 추정
- 영양성분이 이미 DB에 있으면 재사용
- 없으면 LLM 또는 fallback 로직으로 추정 후 저장

영양성분 추정 흐름:

```text
음식명 + 분량
→ food_nutrition_estimates 캐시 조회
→ 캐시 없음
→ OpenAI LLM으로 영양성분 추정
→ 실패 시 fallback 값 사용
→ DB 저장
```

## 5. 하루 영양 리포트

하루 리포트는 `GET /api/fitlog/reports/daily?date=...` API로 생성됩니다.

관련 함수:

- `build_daily_report()`

계산 항목:

- 총 칼로리
- 남은 칼로리
- 탄수화물 총량
- 단백질 총량
- 지방 총량
- 식사 개수
- 목표 초과 여부
- 단백질 부족 등 warning

이 리포트는 단순 화면 표시용만이 아니라, 전략 Agent의 입력 데이터로도 사용됩니다.

## 6. RAG 구현

이 프로젝트에서 RAG는 **식단 전략 생성용 영양 지식 검색 기능**으로 구현되어 있습니다.

RAG의 역할:

> 사용자의 하루 식단 상태와 질문에 맞는 영양 지식 문서를 검색하고, 그 검색 결과를 LLM 전략 생성에 근거 자료로 제공

관련 코드:

- `backend/app/services/fitlog.py`
- `NutritionKnowledgeDoc`
- `nutrition_knowledge_docs`

RAG 검색 대상:

- 기본 영양 지식 문서
- 단백질 섭취
- 나트륨 주의
- 목표 칼로리 초과 시 조절 전략
- 지방 섭취 균형

RAG 구현 흐름:

```text
영양 지식 문서
→ OpenAI embedding 생성
→ PostgreSQL pgvector에 저장
→ 사용자 질문 + 하루 리포트 상태를 query로 구성
→ query embedding 생성
→ pgvector cosine distance 비교
→ top-k 관련 문서 검색
→ LLM 프롬프트에 RAG evidence로 포함
```

핵심 함수:

- `ensure_knowledge()`
  - 기본 영양 지식 문서가 DB에 없으면 저장

- `ensure_knowledge_embeddings()`
  - embedding이 없는 문서를 OpenAI embedding으로 변환

- `langchain_text_embedding()`
  - LangChain의 `OpenAIEmbeddings`를 이용해 텍스트를 벡터화

- `search_knowledge()`
  - query embedding과 문서 embedding을 pgvector로 비교해 top-k 문서 검색

핵심 SQL:

```sql
ORDER BY embedding <=> CAST(:embedding AS vector)
LIMIT :limit
```

여기서 `<=>`는 pgvector의 cosine distance 연산자입니다. 값이 작을수록 더 유사한 문서입니다.

정리하면:

> 현재 RAG는 OpenAI Embedding + PostgreSQL pgvector + LangChain OpenAIEmbeddings를 이용한 텍스트 기반 전략 지식 검색 기능입니다.

## 7. AI Agent 구현

이 프로젝트에서 AI Agent는 **FitLog Diet Strategy Agent**로 구현되어 있습니다.

Agent의 역할:

> 사용자의 목표와 식단 기록을 조회하고, 하루 리포트를 만들고, RAG로 관련 지식을 검색한 뒤, LLM을 호출해 오늘/내일 식단 전략을 생성하고 저장

관련 코드:

- `backend/app/services/fitlog.py`
- `FitLogDietStrategyAgent`
- `create_strategy()`
- `generate_strategy_text()`

Agent 실행 흐름:

```text
agent_start
→ get_active_goal
→ build_daily_report
→ search_nutrition_knowledge
→ generate_strategy
→ save_strategy
```

각 단계의 역할:

- `get_active_goal`
  - 사용자의 현재 목표 체중, 목표 날짜, 하루 목표 칼로리를 조회

- `build_daily_report`
  - 해당 날짜의 식단 기록을 바탕으로 하루 영양 상태 계산

- `search_nutrition_knowledge`
  - RAG 검색기로 관련 영양 지식 문서 검색

- `generate_strategy`
  - 식단 리포트와 RAG 근거를 LLM에게 전달해 전략 생성

- `save_strategy`
  - 생성된 전략과 Agent 실행 기록을 DB에 저장

저장되는 결과:

- 오늘 전략
- 내일 전략
- 위험 메모
- RAG 근거 문서
- Agent 실행 단계 기록

현재 Agent의 성격:

> 완전 자율형 Agent라기보다는, 코드가 정한 순서대로 도구를 실행하는 workflow-style AI Agent입니다.

발표에서 표현하면:

> 이 프로젝트의 AI Agent는 목표 달성을 위해 식단 조회, 리포트 생성, RAG 검색, LLM 전략 생성, DB 저장을 하나의 실행 흐름으로 조합한 Diet Strategy Agent입니다.

## 8. MCP 구현

이 프로젝트에서 MCP는 **외부 AI Agent가 FitLog 기능을 도구처럼 호출할 수 있게 하는 연결 계층**으로 구현되어 있습니다.

관련 코드:

- `mcp_server/src/index.js`
- `mcp_server/src/fitlogClient.js`

MCP의 역할:

> 외부 AI 애플리케이션이 FitLog API를 직접 알지 않아도, 표준 MCP tool 형태로 식단 기록과 전략 기능을 호출할 수 있게 함

제공하는 MCP tool:

- `get_daily_meals(date)`
  - 특정 날짜의 식단 기록 조회

- `get_daily_report(date)`
  - 특정 날짜의 하루 영양 리포트 조회

- `get_strategy_history(date)`
  - 생성된 전략 기록 조회

- `create_strategy(date, question)`
  - FitLog Diet Strategy Agent를 호출해 새 전략 생성

MCP 흐름:

```text
외부 AI Agent
→ MCP tool 호출
→ mcp_server
→ FitLog FastAPI 호출
→ 식단/리포트/전략 결과 반환
```

중요한 점:

- MCP는 DB를 직접 조회하지 않음
- 기존 FastAPI 기능을 감싸서 외부 AI에 tool로 제공
- RAG나 Agent 자체가 아니라, 외부 AI와 서비스 기능을 연결하는 프로토콜 계층

발표에서 표현하면:

> MCP는 외부 AI Agent가 우리 서비스의 식단 기록, 하루 리포트, 전략 생성 기능을 표준 도구처럼 사용할 수 있게 하는 연결망으로 구현했습니다.

## 9. 이미지 음식 분석 구현

이미지 기능은 현재 엄밀한 의미의 이미지 RAG가 아니라, **ResNet-34 음식 분류 기반 식단 입력 보조 기능**으로 구현되어 있습니다.

관련 코드:

- `backend/app/services/fitlog_food_classifier.py`
- `backend/app/services/fitlog_image_rag.py`
- `backend/app/api/fitlog_image_rag.py`
- `frontend/src/screens/FitlogMealFormPage.tsx`

Frontend 흐름:

```text
Add meal
→ 이미지 선택
→ crop 영역 선택 가능
→ 음식 분석 버튼 클릭
→ top-k 음식 후보 표시
→ 후보 선택 시 Foods에 자동 반영
```

Backend 흐름:

```text
이미지 업로드
→ ResNet-34 checkpoint 로드
→ 이미지 전처리
→ model forward
→ softmax
→ top-k 음식 라벨 + confidence 반환
→ 음식명으로 영양성분 조회/추정
→ 프론트에 후보 반환
```

confidence 기준:

- `0.8` 이상
  - 자동 채택

- `0.5` 이상 `0.8` 미만
  - 사용자 확인 필요

- `0.5` 미만
  - 수동 입력 필요, 추후 학습 후보 저장 대상

중요한 설계 판단:

> 이미지 벡터와 텍스트 임베딩은 같은 공간이 아니므로 직접 비교하지 않습니다. 먼저 ResNet으로 음식명을 분류한 뒤, 그 음식명을 텍스트 기반 영양 추정/RAG 흐름에 연결합니다.

## 10. DB에서 사용되는 주요 테이블

FitLog 관련 주요 테이블:

- `goal_profiles`
  - 사용자 목표 정보

- `meal_logs`
  - 날짜별 식단 기록

- `meal_food_items`
  - 식단에 포함된 음식 항목

- `food_nutrition_estimates`
  - 음식명/분량별 영양성분 추정 캐시

- `nutrition_knowledge_docs`
  - RAG 검색 대상 영양 지식 문서

- `strategy_advices`
  - 생성된 식단 전략 기록

추가 예정:

- `food_image_training_candidates`
  - confidence가 낮은 이미지와 사용자 확정 라벨을 저장해 재학습 후보로 사용

## 11. 발표용 비교 정리

| 구분 | 이 프로젝트에서의 구현 |
|---|---|
| RAG | 영양 지식 문서를 embedding하고 pgvector로 검색해 전략 생성 LLM에 근거로 제공 |
| AI Agent | 목표 조회, 리포트 생성, RAG 검색, LLM 전략 생성, DB 저장을 수행하는 Diet Strategy Agent |
| MCP | 외부 AI Agent가 FitLog API를 tool처럼 호출할 수 있게 하는 표준 연결 서버 |
| ResNet | 음식 이미지를 음식명 후보로 분류하고 Add meal 입력을 보조 |
| LLM | 음식 영양성분 추정과 식단 전략 생성에 사용 |
| pgvector | 전략 RAG 문서 embedding 검색에 사용 |

## 12. 현재 한계와 남은 작업

현재 남은 작업:

- 낮은 confidence 이미지와 사용자 확정 라벨 저장
- `food_image_training_candidates` 모델과 migration 추가
- 이미지 분석 결과를 재학습 데이터로 export하는 기능
- Docker 환경에 torch/torchvision/Pillow 설치 전략 반영
- 기존 `/api/fitlog/image-search-test` placeholder 정리
- `backend/app/services/fitlog.py`의 legacy 코드 정리
- 한글 깨짐이 있는 fallback 문구 정리

## 13. 발표용 핵심 문장

이 프로젝트는 게시판 서비스에 FitLog 기능을 추가하고, 사용자의 식단 기록을 기반으로 하루 영양 리포트를 생성합니다. 이후 OpenAI embedding과 pgvector를 이용한 RAG 검색으로 관련 영양 지식을 찾고, FitLog Diet Strategy Agent가 LLM을 호출해 개인화된 오늘/내일 식단 전략을 생성합니다. 또한 MCP 서버를 통해 외부 AI Agent가 FitLog 데이터를 도구처럼 조회하고 전략 생성을 호출할 수 있도록 구현했으며, ResNet-34 음식 이미지 분류를 통해 식단 입력을 보조하는 기능도 추가했습니다.
