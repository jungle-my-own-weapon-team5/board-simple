# FitLog 아키텍처

## 1. 전체 구조

FitLog는 기존 게시판 서비스에 식단 기록, 하루 영양 리포트, 전략 생성, 이미지 음식 분석, MCP 연결을 추가한 구조입니다.

```text
사용자
  ↓
Next.js Frontend
  ↓ fetch / credentials: include
FastAPI Backend
  ↓ SQLAlchemy ORM
PostgreSQL + pgvector

외부 연동:
FastAPI Backend → OpenAI API
FastAPI Backend → ResNet-34 음식 분류 모델
External AI Agent → MCP Server → FastAPI Backend
```

## 2. 런타임 구성

Docker Compose 기준 서비스는 다음과 같습니다.

| 서비스 | 역할 |
|---|---|
| `frontend` | Next.js UI 서버, 기본 포트 `3000` |
| `backend` | FastAPI API 서버, 기본 포트 `8000` |
| `db` | `pgvector/pgvector:pg16` PostgreSQL |
| `migrate` | Alembic migration 실행 |

파일 업로드는 DB에 바이너리로 저장하지 않고, `backend/uploads`에 파일로 저장합니다.

```text
Docker volume
./backend/uploads → /app/backend/uploads
```

업로드된 이미지는 FastAPI에서 `/uploads/...` 정적 파일로 제공합니다.

## 3. Frontend 아키텍처

Frontend는 Next.js App Router 기반입니다.

주요 위치:

| 위치 | 역할 |
|---|---|
| `frontend/src/app/fitlog/*` | FitLog 라우트 |
| `frontend/src/screens/*` | 화면 단위 컴포넌트 |
| `frontend/src/api/fitlog.ts` | FitLog API client |
| `frontend/src/api/client.ts` | 공통 `fetch` wrapper |
| `frontend/src/components/ImageCropPicker.tsx` | 이미지 업로드 및 crop 선택 |
| `frontend/src/components/FitlogCoachButton.tsx` | 오른쪽 하단 Coach Agent 창 |

Frontend API 호출은 `NEXT_PUBLIC_API_BASE_URL`을 기준으로 수행합니다.

```text
Next.js 화면
  ↓
frontend/src/api/fitlog.ts
  ↓
frontend/src/api/client.ts
  ↓
FastAPI /api/fitlog/*
```

인증 쿠키를 사용하기 때문에 `fetch`는 `credentials: "include"`로 호출합니다.

## 4. Backend 아키텍처

Backend는 FastAPI + SQLAlchemy ORM + Pydantic schema 구조입니다.

주요 위치:

| 위치 | 역할 |
|---|---|
| `backend/app/main.py` | FastAPI 앱 생성, router 등록, uploads 정적 파일 mount |
| `backend/app/api/fitlog.py` | FitLog 목표, 식단, 리포트, 전략 API |
| `backend/app/api/fitlog_image_rag.py` | 이미지 음식 분석 API |
| `backend/app/services/fitlog.py` | 식단 계산, 영양 추정, RAG, AI Agent 핵심 로직 |
| `backend/app/services/fitlog_image_rag.py` | 이미지 분류 결과 라우팅 |
| `backend/app/services/fitlog_food_classifier.py` | ResNet-34 음식 분류 모델 로딩/추론 |
| `backend/app/services/uploads.py` | 업로드 파일 저장 |
| `backend/app/models/fitlog.py` | FitLog SQLAlchemy 모델 |
| `backend/app/schemas/fitlog.py` | FitLog API 입출력 schema |

Backend router 등록 구조:

```text
/api/auth
/api/posts
/api/comments
/api/tags
/api/fitlog
/api/fitlog/image-rag
/uploads
```

## 5. 주요 데이터 모델

FitLog에서 사용하는 주요 테이블은 다음과 같습니다.

| 테이블 | 역할 |
|---|---|
| `goal_profiles` | 사용자 목표 체중, 목표 날짜, 하루 목표 칼로리 |
| `meal_logs` | 날짜, 식사 타입, 시간, 메모, 대표 이미지, 총 영양성분 |
| `meal_food_items` | 식단에 포함된 개별 음식, 분량, 영양성분, 음식별 이미지 |
| `food_nutrition_estimates` | 음식명 + 단위 기준 영양성분 캐시 |
| `nutrition_knowledge_docs` | 전략 RAG용 영양 지식 문서 |
| `strategy_advices` | 생성된 식단 전략, RAG 근거, Agent 실행 trace |

이미지 검색용으로 계획된 `food_image_training_candidates`, `food_image_embeddings`는 현재 실제 migration/table이 아니라 향후 확장 위치로만 남아 있습니다.

## 6. 식단 기록 흐름

```text
사용자 식단 입력
  ↓
POST /api/fitlog/meals
  ↓
이미지 / crop 이미지 저장
  ↓
foods_json 파싱
  ↓
음식명 + 분량 기준 영양성분 조회
  ↓
food_nutrition_estimates 캐시 hit → 재사용
  ↓
캐시 miss → LLM 영양성분 추정 후 DB 저장
  ↓
meal_logs / meal_food_items 저장
```

아침, 점심, 저녁은 같은 날짜에 하나만 유지하는 방식이고, 다시 등록하면 기존 데이터를 교체합니다. 간식은 여러 개 등록할 수 있고 시간순으로 정렬됩니다.

## 7. 하루 리포트 흐름

```text
GET /api/fitlog/reports/daily?date=YYYY-MM-DD
  ↓
build_daily_report()
  ↓
meal_logs + meal_food_items 집계
  ↓
총 칼로리 / 탄수화물 / 단백질 / 지방 계산
  ↓
목표 대비 상태와 warning 생성
```

이 리포트는 화면 표시용이면서, AI Agent 전략 생성의 입력 데이터로도 사용됩니다.

## 8. RAG 아키텍처

이 프로젝트의 RAG는 식단 전략 생성에 필요한 영양 지식 검색기로 구현되어 있습니다.

```text
기본 영양 지식 문서
  ↓
OpenAI Embedding 생성
  ↓
nutrition_knowledge_docs.embedding vector(1536) 저장

사용자 질문 + 하루 리포트 상태
  ↓
OpenAI Embedding 생성
  ↓
pgvector cosine distance 검색
  ↓
top-k 지식 문서 반환
  ↓
LLM 전략 생성 prompt에 evidence로 포함
```

핵심 구현:

| 함수 | 역할 |
|---|---|
| `ensure_knowledge()` | 기본 영양 지식 문서 준비 |
| `ensure_knowledge_embeddings()` | 문서 embedding 생성 |
| `langchain_text_embedding()` | LangChain `OpenAIEmbeddings` 사용 |
| `search_knowledge()` | pgvector 기반 top-k 검색 |

pgvector 검색은 cosine distance 연산자인 `<=>`를 사용합니다.

## 9. AI Agent 아키텍처

AI Agent는 `FitLogDietStrategyAgent` 클래스로 구현되어 있습니다.

```text
POST /api/fitlog/strategy
  ↓
create_strategy()
  ↓
FitLogDietStrategyAgent.run()
  ↓
agent_start
  ↓
get_active_goal
  ↓
build_daily_report
  ↓
search_nutrition_knowledge
  ↓
generate_strategy
  ↓
save_strategy
```

Agent의 특징:

| 단계 | 역할 |
|---|---|
| `get_active_goal` | 사용자 목표 조회 |
| `build_daily_report` | 하루 식단 상태 계산 |
| `search_nutrition_knowledge` | RAG 지식 검색 |
| `generate_strategy` | OpenAI Responses API로 전략 생성 |
| `save_strategy` | 결과와 agent trace 저장 |

결과는 `StrategyResponse`로 반환되며, `agent_steps`에 실행 단계가 기록됩니다.

## 10. MCP 아키텍처

MCP는 외부 AI Agent가 FitLog 기능을 tool처럼 호출할 수 있게 하는 연결 계층입니다.

```text
External AI Agent / MCP Client
  ↓ MCP stdio JSON-RPC
backend/app/mcp/server.py
  ↓ tool call
backend/app/mcp/tools.py
  ↓ service function call
FitLog service layer
```

제공 tool:

| MCP tool | 내부 호출 |
|---|---|
| `get_daily_meals(date)` | `MealLog` 조회 후 `MealLogRead` 직렬화 |
| `get_daily_report(date)` | `build_daily_report(db, user_id, date)` |
| `get_strategy_history(date?)` | `StrategyAdvice` 조회 후 `StrategyAdviceRead` 직렬화 |
| `create_strategy(date, question?)` | `create_strategy(db, user_id, date, question)` |

MCP 서버는 FastAPI HTTP endpoint를 다시 호출하지 않고 Python service layer를 직접 재사용합니다. stdio MCP에는 FastAPI request context가 없으므로 현재 사용자는 `FITLOG_MCP_USER_ID` 환경변수로 지정합니다.

## 11. 이미지 음식 분석 아키텍처

현재 이미지 음식 분석은 이미지 벡터 RAG가 아니라 ResNet-34 분류 라벨 기반 검색기로 구현되어 있습니다.

```text
Add meal 이미지 업로드
  ↓
canvas crop 선택
  ↓
crop이 있으면 crop Blob, 없으면 원본 이미지
  ↓
POST /api/fitlog/image-rag/search
  ↓
ResNet-34 음식 분류
  ↓
softmax top-k 후보 생성
  ↓
confidence threshold 분기
  ↓
후보 음식명으로 영양성분 조회/추정
  ↓
Foods에 후보 반영
```

confidence 기준:

| 조건 | 동작 |
|---|---|
| `>= 0.8` | 첫 후보 자동 반영 |
| `>= 0.5` | 사용자 확인 후 반영 |
| `< 0.5` | 수동 라벨 필요, 향후 학습 후보로 저장 예정 |

관련 설정:

| 환경변수 | 기본값 |
|---|---|
| `FOOD_CLASSIFIER_MODEL_PATH` | `app/services/resnet34_food_fc_only.pt` |
| `FOOD_CLASSIFIER_DEVICE` | `auto` |
| `FOOD_CLASSIFIER_TOP_K` | `3` |
| `FOOD_CLASSIFIER_AUTO_ACCEPT_THRESHOLD` | `0.8` |
| `FOOD_CLASSIFIER_USER_CONFIRM_THRESHOLD` | `0.5` |

## 12. OpenAI 사용 지점

| 사용처 | 목적 |
|---|---|
| 음식 영양성분 추정 | 음식명과 분량을 바탕으로 칼로리, 탄수화물, 단백질, 지방 추정 |
| RAG embedding | 전략 지식 문서와 query를 같은 embedding 공간에 배치 |
| 전략 생성 | 하루 리포트와 RAG 근거 기반으로 오늘/내일 식단 전략 생성 |

주요 환경변수:

| 환경변수 | 역할 |
|---|---|
| `OPENAI_API_KEY` | OpenAI API 호출 키 |
| `OPENAI_STRATEGY_AGENT_MODEL` | 전략 생성 LLM |
| `OPENAI_FALLBACK_MODEL` | 영양성분 추정 fallback LLM |
| `OPENAI_EMBEDDING_MODEL` | RAG embedding 모델 |
| `OPENAI_EMBEDDING_DIMENSIONS` | embedding 차원, 기본 `1536` |

## 13. 발표용 핵심 정리

```text
FitLog는 식단 기록 서비스 위에 RAG, AI Agent, MCP, 이미지 분류를 얹은 구조입니다.

RAG:
  OpenAI Embedding + PostgreSQL pgvector로 영양 지식 문서를 검색합니다.

AI Agent:
  목표 조회, 하루 리포트 생성, RAG 검색, LLM 전략 생성, DB 저장을 하나의 실행 흐름으로 묶습니다.

MCP:
  외부 AI Agent가 FitLog API를 표준 tool처럼 호출할 수 있게 합니다.

이미지 검색기:
  ResNet-34가 음식 사진을 분류하고, 분류된 음식명을 영양성분 조회 흐름에 연결합니다.
```

## 14. 관련 발표 자료 파일

| 파일 | 내용 |
|---|---|
| `docs/fitlog-rag-workflow.drawio` | RAG 검색 흐름 |
| `docs/fitlog-ai-agent-workflow.drawio` | AI Agent 실행 흐름 |
| `docs/fitlog-mcp-workflow.drawio` | MCP 연결 흐름 |
| `docs/fitlog-image-search-workflow.drawio` | 이미지 음식 분석 흐름 |
