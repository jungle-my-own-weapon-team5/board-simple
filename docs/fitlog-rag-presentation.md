# FitLog RAG 발표자료

## Slide 1. 주제

### FitLog Diet Strategy RAG

사용자의 식단 기록과 하루 영양 상태를 기반으로 관련 영양 지식을 검색하고, 그 검색 결과를 LLM에 전달해 개인화된 식단 전략을 생성하는 RAG 구조입니다.

발표 핵심 문장:

> FitLog의 RAG는 음식 이미지를 직접 벡터 검색하는 기능이 아니라, 하루 식단 상태와 사용자 질문에 맞는 영양 지식 문서를 검색해서 전략 생성 Agent의 근거로 사용하는 구조입니다.

---

## Slide 2. RAG를 왜 사용했는가

LLM만 사용하면 다음 문제가 있습니다.

- 사용자의 하루 식단 상태와 목표를 안정적으로 반영하기 어렵습니다.
- 단백질 부족, 칼로리 초과, 식사 조절 같은 기준을 매번 프롬프트에 직접 넣어야 합니다.
- 서비스가 가진 영양 지식과 전략 기준을 재사용하기 어렵습니다.

그래서 FitLog는 다음 구조를 사용합니다.

```text
사용자 질문 + 하루 식단 리포트
  ↓
관련 영양 지식 검색
  ↓
검색된 근거를 LLM prompt에 포함
  ↓
오늘/내일 식단 전략 생성
```

---

## Slide 3. 전체 RAG 흐름

```text
사용자
  ↓
Coach UI 또는 Generate strategy
  ↓
POST /api/fitlog/strategy
  ↓
FitLogDietStrategyAgent
  ↓
하루 식단 리포트 생성
  ↓
RAG query 생성
  ↓
OpenAI Embedding
  ↓
PostgreSQL pgvector 검색
  ↓
top-k 영양 지식 문서
  ↓
OpenAI Responses API
  ↓
개인화 식단 전략 저장 및 반환
```

관련 흐름도:

- `docs/fitlog-rag-workflow.drawio`
- `docs/fitlog-ai-agent-workflow.drawio`

---

## Slide 4. RAG의 검색 대상

검색 대상은 음식 사진이 아니라 `nutrition_knowledge_docs` 테이블의 영양 지식 문서입니다.

테이블 역할:

| 컬럼 | 역할 |
|---|---|
| `title` | 지식 문서 제목 |
| `category` | 문서 분류 |
| `content` | 실제 영양 지식 내용 |
| `source_url` | 출처 URL, 선택값 |
| `embedding` | OpenAI embedding 결과 |

예시 지식:

- 목표 칼로리를 초과한 날의 조절 전략
- 단백질 부족 시 보완 전략
- 나트륨이 높은 식단의 주의점
- 지방 섭취 균형
- 식단 페이스 조절 기준

---

## Slide 5. 문서 임베딩 저장

FitLog는 기본 영양 지식 문서를 DB에 준비한 뒤, embedding이 없는 문서를 OpenAI Embedding API로 벡터화합니다.

구현 함수:

| 함수 | 역할 |
|---|---|
| `ensure_knowledge()` | 기본 영양 지식 문서가 없으면 DB에 생성 |
| `ensure_knowledge_embeddings()` | embedding이 없는 문서를 벡터화 |
| `langchain_text_embedding()` | LangChain `OpenAIEmbeddings`로 텍스트 embedding 생성 |

현재 사용 구조:

```text
영양 지식 텍스트
  ↓
LangChain OpenAIEmbeddings
  ↓
1536차원 vector
  ↓
PostgreSQL pgvector 컬럼에 저장
```

---

## Slide 6. Query는 어떻게 만들어지는가

사용자 질문만 검색어로 쓰지 않고, 하루 리포트 상태를 함께 조합합니다.

구현 위치:

- `backend/app/services/fitlog.py`
- `FitLogDietStrategyAgent.retrieve_evidence()`

검색 query 구성:

```text
사용자 질문
+ 하루 리포트 warning
+ 하루 리포트 status
```

예시:

```text
"오늘 목표 달성을 위해 무엇을 조정해야 하나요?"
+ "단백질이 부족합니다"
+ "calorie_over"
```

이렇게 하면 단순 질문보다 현재 식단 상태에 맞는 지식 문서를 찾을 수 있습니다.

---

## Slide 7. pgvector 검색 방식

검색은 PostgreSQL의 pgvector 확장을 사용합니다.

핵심 개념:

```text
query embedding
  vs
문서 embedding
```

유사도 비교는 cosine distance 기반입니다.

핵심 SQL:

```sql
ORDER BY embedding <=> CAST(:embedding AS vector)
LIMIT :limit
```

여기서 `<=>`는 pgvector의 cosine distance 연산자입니다.

- 값이 작을수록 더 유사합니다.
- top-k 문서를 선택합니다.
- 검색된 문서는 `RagEvidence`로 변환됩니다.

---

## Slide 8. 검색 결과는 어떻게 쓰이는가

검색 결과는 LLM에게 그대로 정답으로 반환되지 않습니다.

대신 전략 생성 prompt의 근거 자료로 들어갑니다.

```text
RAG 검색 결과
  ↓
RagEvidence[]
  ↓
LLM prompt.evidence
  ↓
LLM이 오늘/내일 전략 생성
```

전달되는 prompt 구성:

| 입력 | 내용 |
|---|---|
| `goal` | 현재 체중, 목표 체중, 목표 날짜, 하루 목표 칼로리 |
| `report` | 하루 총 칼로리, 탄단지, 식사 수, warning |
| `question` | 사용자의 질문 |
| `evidence` | RAG로 검색한 영양 지식 문서 |

---

## Slide 9. 생성기 역할

생성기는 OpenAI Responses API입니다.

구현 함수:

- `generate_strategy_text()`

LLM에게 요구하는 출력 형식:

```json
{
  "pace_status": "...",
  "summary": "...",
  "today_strategy": "...",
  "tomorrow_strategy": "...",
  "risk_notes": ["..."]
}
```

중요한 점:

- LLM은 RAG 검색 결과를 참고합니다.
- 의료 진단을 하지 않도록 system prompt로 제한합니다.
- 응답은 `StrategyResponse`로 검증됩니다.
- 생성 결과는 `strategy_advices` 테이블에 저장됩니다.

---

## Slide 10. AI Agent와 RAG의 관계

RAG는 단독 기능이 아니라 AI Agent 내부 도구로 사용됩니다.

`FitLogDietStrategyAgent` 실행 순서:

```text
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

여기서 RAG는 `search_nutrition_knowledge` 단계입니다.

Agent는 다음 결과를 함께 저장합니다.

- 생성된 전략
- RAG 근거 문서
- Agent 실행 단계 trace

---

## Slide 11. RAG 구현 코드 위치

주요 파일:

| 파일 | 역할 |
|---|---|
| `backend/app/services/fitlog.py` | RAG, 리포트, Agent, 전략 생성 핵심 로직 |
| `backend/app/models/fitlog.py` | `NutritionKnowledgeDoc`, `StrategyAdvice` 모델 |
| `backend/app/api/fitlog.py` | `/api/fitlog/strategy` API |
| `backend/app/schemas/fitlog.py` | `RagEvidence`, `StrategyResponse`, `AgentStep` schema |

핵심 함수:

| 함수 | 역할 |
|---|---|
| `ensure_knowledge()` | 기본 지식 문서 준비 |
| `ensure_knowledge_embeddings()` | 문서 embedding 생성 |
| `langchain_text_embedding()` | OpenAI embedding 호출 |
| `search_knowledge()` | pgvector top-k 검색 |
| `generate_strategy_text()` | RAG 근거 기반 LLM 생성 |
| `create_strategy()` | Agent 실행 진입점 |

---

## Slide 12. 현재 구현의 정확한 범위

현재 RAG로 구현된 것:

- 전략 생성을 위한 텍스트 지식 문서 검색
- OpenAI embedding 사용
- PostgreSQL pgvector 저장 및 검색
- 검색 결과를 LLM prompt에 evidence로 전달
- 생성된 전략과 RAG 근거를 DB에 저장

현재 RAG가 아닌 것:

- 음식 사진 자체를 벡터화해서 이미지끼리 검색하는 기능
- ResNet feature vector와 OpenAI text embedding을 직접 비교하는 기능
- OpenAI vector store에 파일을 올려 `file_search`로 검색하는 방식

이미지 음식 분석은 별도 구조입니다.

```text
이미지
  ↓
ResNet-34 음식 분류
  ↓
음식명 후보
  ↓
영양성분 조회/추정
```

---

## Slide 13. RAG, Agent, MCP 구분

| 구분 | 이 프로젝트에서의 역할 |
|---|---|
| RAG | 관련 영양 지식 문서를 검색해서 LLM 전략 생성의 근거로 제공 |
| AI Agent | 목표 조회, 리포트 생성, RAG 검색, LLM 생성, DB 저장을 실행하는 주체 |
| MCP | 외부 AI Agent가 FitLog API를 tool처럼 호출할 수 있게 하는 연결 계층 |
| ResNet | 음식 이미지를 음식명 후보로 분류하는 이미지 입력 보조 기능 |

한 문장 정리:

> RAG는 지식을 찾아오고, Agent는 그 지식을 포함해 작업을 수행하며, MCP는 외부 AI가 이 기능을 호출할 수 있게 연결합니다.

---

## Slide 14. 발표용 최종 요약

FitLog의 RAG는 사용자의 하루 식단 상태를 더 잘 반영하기 위해 구현했습니다.

사용자가 전략 생성을 요청하면, 시스템은 먼저 식단 기록을 집계해 하루 리포트를 만들고, 그 리포트의 warning과 사용자 질문을 조합해 검색 query를 만듭니다.

이 query는 OpenAI Embedding으로 벡터화되고, PostgreSQL pgvector에 저장된 영양 지식 문서 embedding과 cosine distance로 비교됩니다.

가장 관련 있는 top-k 문서는 LLM prompt의 evidence로 들어가고, LLM은 목표, 리포트, 질문, RAG 근거를 함께 보고 오늘과 내일의 식단 전략을 생성합니다.

생성 결과는 `strategy_advices`에 저장되고, 어떤 RAG 근거가 사용됐는지와 Agent가 어떤 단계를 실행했는지도 함께 기록됩니다.

---

## Slide 15. 발표 중 예상 질문 대응

### Q. 이 프로젝트에서 RAG는 어디에 있나요?

`backend/app/services/fitlog.py`의 `search_knowledge()`가 RAG 검색기이고, `generate_strategy_text()`가 검색 결과를 받아 생성기로 넘기는 부분입니다.

### Q. pgvector는 어디에 쓰나요?

`nutrition_knowledge_docs.embedding`에 영양 지식 문서 embedding을 저장하고, query embedding과 cosine distance로 비교하는 데 사용합니다.

### Q. 이미지 검색도 RAG인가요?

현재는 아닙니다. 현재 이미지 기능은 ResNet-34 분류기로 음식명을 추정하는 구조입니다. 이미지 벡터 검색 RAG는 향후 확장 영역입니다.

### Q. LangChain은 어디에 쓰나요?

OpenAI embedding 호출을 `LangChain OpenAIEmbeddings`로 감싼 부분에 사용합니다.

### Q. LLM은 검색을 직접 하나요?

아닙니다. 검색은 서버가 pgvector로 먼저 수행하고, LLM은 검색된 결과를 prompt의 근거로 받아 전략을 생성합니다.

