# FitLog MCP 발표자료

## Slide 1. 주제

### FitLog Context MCP

FitLog의 MCP는 외부 AI Agent가 우리 서비스의 식단 기록, 하루 리포트, 전략 생성 기능을 표준 tool처럼 호출할 수 있게 하는 연결 계층입니다.

발표 핵심 문장:

> 이 프로젝트에서 MCP는 별도 Node 서버가 아니라 Python 백엔드 내부의 MCP 서버로 구현했습니다. FastAPI와 같은 서비스 계층을 재사용해 외부 AI Agent가 FitLog 기능을 tool처럼 호출할 수 있게 합니다.

---

## Slide 2. 왜 Python MCP로 구현했는가

처음에는 MCP를 별도 Node adapter로 둘 수도 있지만, 이 프로젝트에서는 Python 백엔드에 두는 편이 더 자연스럽습니다.

이유:

- 핵심 비즈니스 로직이 이미 FastAPI/Python에 있습니다.
- `build_daily_report()`, `create_strategy()`, `FitLogDietStrategyAgent`를 직접 재사용할 수 있습니다.
- HTTP로 한 번 더 우회하지 않아도 됩니다.
- SQLAlchemy session과 Pydantic schema를 그대로 사용할 수 있습니다.
- 발표할 때 기술스택 설명이 단순해집니다.

현재 구조:

```text
External AI Agent
  ↓ MCP stdio JSON-RPC
Python MCP Server
  ↓ 직접 service 함수 호출
FitLog service layer
  ↓
PostgreSQL / RAG / LLM
```

---

## Slide 3. 전체 MCP 흐름

```text
External AI Agent / MCP Client
  ↓
MCP stdio JSON-RPC
  ↓
backend/app/mcp/server.py
  ↓
tools/list 또는 tools/call
  ↓
backend/app/mcp/tools.py
  ↓
FitLog service functions
  ↓
SQLAlchemy / PostgreSQL / RAG / AI Agent
```

관련 흐름도:

- `docs/fitlog-mcp-workflow.drawio`

---

## Slide 4. 구현 위치

MCP 구현은 `backend/app/mcp/` 폴더에 있습니다.

| 파일 | 역할 |
|---|---|
| `backend/app/mcp/server.py` | MCP stdio JSON-RPC 처리, tool 목록 제공, tool 호출 라우팅 |
| `backend/app/mcp/tools.py` | FitLog MCP tool 구현, DB session과 service 함수 호출 |
| `backend/app/mcp/smoke.py` | MCP initialize, tools/list 동작 확인 |
| `backend/app/mcp/README.md` | 실행 방법과 MCP client 설정 예시 |

핵심 구조:

```text
server.py
  initialize / ping / tools/list / tools/call 처리
  Content-Length 기반 stdio message 처리

tools.py
  사용자 ID 확인
  날짜 입력 검증
  DB session으로 FitLog service layer 호출
```

---

## Slide 5. MCP 서버가 제공하는 Tool

현재 제공하는 MCP tool은 4개입니다.

| MCP tool | 역할 |
|---|---|
| `get_daily_meals(date)` | 특정 날짜 식단 기록 조회 |
| `get_daily_report(date)` | 특정 날짜 하루 영양 리포트 조회 |
| `get_strategy_history(date?)` | 생성된 전략 기록 조회 |
| `create_strategy(date, question?)` | FitLog Diet Strategy Agent를 호출해 전략 생성 |

이 tool들은 외부 Agent에게 FitLog 기능을 표준 도구처럼 보여줍니다.

---

## Slide 6. Tool과 내부 함수 매핑

Python MCP 서버는 FastAPI HTTP endpoint를 다시 호출하지 않고 내부 service layer를 직접 사용합니다.

| MCP tool | 내부 호출 |
|---|---|
| `get_daily_meals(date)` | `MealLog` 조회 + `MealLogRead` 직렬화 |
| `get_daily_report(date)` | `build_daily_report(db, user_id, date)` |
| `get_strategy_history(date?)` | `StrategyAdvice` 조회 + `StrategyAdviceRead` 직렬화 |
| `create_strategy(date, question?)` | `create_strategy(db, user_id, date, question)` |

구조적으로 보면:

```text
MCP tool
  ↓
backend/app/mcp/tools.py
  ↓
backend/app/services/fitlog.py
  ↓
SQLAlchemy ORM
```

---

## Slide 7. MCP Protocol 처리

`server.py`는 MCP의 JSON-RPC 요청을 처리합니다.

처리하는 method:

| method | 역할 |
|---|---|
| `initialize` | MCP 서버 정보와 capabilities 반환 |
| `ping` | 연결 상태 확인 |
| `tools/list` | 사용 가능한 tool 목록 반환 |
| `tools/call` | 특정 tool 실행 |

서버 정보:

```text
name: fitlog-context-mcp
version: 0.2.0
protocolVersion: 2024-11-05
capabilities: tools
```

---

## Slide 8. 입력 검증

MCP server는 tool 호출 전에 최소한의 입력 검증을 합니다.

검증 내용:

- 알 수 없는 tool 이름이면 에러 반환
- `date`는 `YYYY-MM-DD` 문자열이어야 함
- `question`은 있으면 문자열이어야 함
- `FITLOG_MCP_USER_ID`가 없으면 tool call을 거부함

예시:

```text
create_strategy
  date: required, YYYY-MM-DD
  question: optional string
  user: FITLOG_MCP_USER_ID
```

---

## Slide 9. 사용자 식별 구조

stdio MCP 서버는 FastAPI HTTP request를 받는 것이 아니기 때문에 기존 `get_current_user` dependency를 그대로 사용할 수 없습니다.

그래서 현재는 MCP 실행 환경에서 사용자 ID를 명시합니다.

| 환경변수 | 역할 |
|---|---|
| `FITLOG_MCP_USER_ID` | MCP tool이 조회할 사용자 ID |
| `DATABASE_URL` | PostgreSQL 연결 주소 |
| `OPENAI_API_KEY` | 전략 생성과 RAG embedding에 필요한 OpenAI key |

현재 구조:

```text
MCP Client
  ↓ env: FITLOG_MCP_USER_ID
Python MCP Server
  ↓
SQLAlchemy session
  ↓
user_id 기준 FitLog 데이터 조회
```

---

## Slide 10. create_strategy Tool 흐름

가장 중요한 tool은 `create_strategy(date, question?)`입니다.

```text
외부 AI Agent
  ↓ create_strategy 호출
Python MCP Server
  ↓
create_strategy(db, user_id, date, question)
  ↓
FitLogDietStrategyAgent.run()
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

MCP는 전략을 직접 생성하는 것이 아니라, 백엔드의 FitLog Diet Strategy Agent를 tool로 노출합니다.

---

## Slide 11. MCP와 RAG, AI Agent의 관계

MCP, RAG, AI Agent는 역할이 다릅니다.

| 구분 | 역할 |
|---|---|
| MCP | 외부 AI Agent가 FitLog 기능을 tool처럼 호출하게 하는 연결 계층 |
| AI Agent | 목표 조회, 리포트 생성, RAG 검색, LLM 생성, DB 저장을 수행 |
| RAG | 전략 생성을 위해 관련 영양 지식 문서를 검색 |
| Service layer | 실제 식단 계산, 전략 생성, DB 접근 담당 |

관계:

```text
External AI Agent
  ↓ MCP
FitLog service layer
  ↓
FitLog Diet Strategy Agent
  ↓
RAG 검색 + LLM 생성
```

---

## Slide 12. Python MCP가 좋은 이유

Python MCP로 바꾸면서 구조가 단순해졌습니다.

기존 Node adapter 방식:

```text
MCP → Node server → HTTP → FastAPI → Service → DB
```

현재 Python MCP 방식:

```text
MCP → Python server → Service → DB
```

장점:

- HTTP wrapper 제거
- FastAPI 백엔드 코드와 같은 언어 사용
- Pydantic schema 재사용
- SQLAlchemy session 직접 사용
- RAG/Agent 로직과 더 가까운 위치에 MCP 배치

---

## Slide 13. MCP Client 설정 예시

외부 MCP Client에서는 이런 형태로 서버를 등록할 수 있습니다.

```json
{
  "mcpServers": {
    "fitlog-context": {
      "command": "python",
      "args": [
        "-m",
        "app.mcp.server"
      ],
      "cwd": "C:/crafton/1/ai_utilization/board_simple/backend",
      "env": {
        "FITLOG_MCP_USER_ID": "1",
        "DATABASE_URL": "postgresql+psycopg://board:board@localhost:5432/board",
        "OPENAI_API_KEY": "..."
      }
    }
  }
}
```

이렇게 등록하면 외부 AI Agent는 FitLog 기능을 tool로 사용할 수 있습니다.

---

## Slide 14. MCP Smoke Test

MCP 서버가 최소 동작하는지는 smoke test로 확인할 수 있습니다.

```powershell
cd backend
python -m app.mcp.smoke
```

테스트 내용:

- Python MCP 서버 실행
- `initialize` 요청 전송
- `tools/list` 요청 전송
- 응답에 `fitlog-context-mcp`가 있는지 확인
- 응답에 `get_daily_meals`, `create_strategy`가 있는지 확인

검증 결과:

```text
Python MCP smoke test passed
```

---

## Slide 15. 현재 구현 범위

현재 구현된 것:

- Python stdio MCP 서버
- JSON-RPC request parsing
- `initialize`, `ping`, `tools/list`, `tools/call`
- FitLog tool 4개 제공
- SQLAlchemy session 기반 service layer 직접 호출
- `FITLOG_MCP_USER_ID` 기반 사용자 선택
- smoke test

현재 구현하지 않은 것:

- MCP OAuth 또는 사용자별 권한 위임
- MCP resource 제공
- MCP tool을 통한 식단 생성/수정
- 장기 세션 관리
- 원격 Streamable HTTP MCP 서버

발표에서는 현재 구현을 “Python 백엔드 service layer를 직접 사용하는 stdio MCP server”라고 설명하는 것이 정확합니다.

---

## Slide 16. 발표용 최종 요약

FitLog MCP는 외부 AI Agent가 서비스 내부 기능을 표준 tool처럼 사용할 수 있게 만든 연결 계층입니다.

MCP 서버는 Python 백엔드 내부의 `backend/app/mcp`에 구현되어 있고, stdio 기반 JSON-RPC 요청을 받습니다.

외부 Agent가 `get_daily_meals`, `get_daily_report`, `get_strategy_history`, `create_strategy` 같은 tool을 호출하면 MCP 서버는 SQLAlchemy session을 열고 기존 FitLog service 함수를 직접 실행합니다.

특히 `create_strategy`는 FitLog Diet Strategy Agent를 실행하며, 그 안에서 하루 리포트 생성, RAG 검색, LLM 전략 생성, DB 저장이 이어집니다.

따라서 이 프로젝트에서 MCP는 RAG나 Agent 자체가 아니라, 외부 AI Agent가 FitLog의 RAG/Agent 기능을 호출할 수 있게 하는 표준 연결 계층입니다.

---

## Slide 17. 발표 중 예상 질문 대응

### Q. MCP는 RAG인가요?

아닙니다. MCP는 검색 기술이 아니라 외부 AI Agent와 서비스 기능을 연결하는 protocol 계층입니다.

### Q. 왜 Node가 아니라 Python으로 구현했나요?

FitLog의 핵심 로직이 FastAPI/Python에 있기 때문입니다. Python MCP는 `build_daily_report`, `create_strategy`, SQLAlchemy session, Pydantic schema를 직접 재사용할 수 있어 구조가 더 단순합니다.

### Q. MCP가 직접 DB를 조회하나요?

MCP tool 구현은 SQLAlchemy session을 사용하지만, 비즈니스 로직은 기존 FitLog service layer를 호출합니다. 즉 DB 접근은 백엔드 서비스 계층 안에서 처리됩니다.

### Q. MCP에서 전략 생성을 직접 하나요?

MCP 자체가 전략을 만들지는 않습니다. `create_strategy` tool이 `FitLogDietStrategyAgent`를 실행합니다.

### Q. 인증은 어떻게 하나요?

현재 stdio MCP 서버는 `FITLOG_MCP_USER_ID` 환경변수로 사용자 ID를 지정합니다. 실제 서비스 수준에서는 OAuth나 사용자별 권한 위임 구조를 추가할 수 있습니다.

### Q. 발표에서 한 문장으로 설명하면?

> MCP는 외부 AI Agent가 FitLog의 식단 기록, 리포트, 전략 생성 기능을 Python 백엔드 tool처럼 호출할 수 있게 만든 연결 계층입니다.

