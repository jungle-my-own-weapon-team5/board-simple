# FitLog Context MCP

FitLog Context MCP는 외부 AI Agent가 FitLog의 식단 기록, 하루 리포트, 전략 기록, 전략 생성 기능을 tool처럼 호출할 수 있게 하는 Python stdio MCP 서버입니다.

## Tools

- `get_daily_meals(date)`: 특정 날짜 식단 기록 조회
- `get_daily_report(date)`: 특정 날짜 하루 영양 리포트 조회
- `get_strategy_history(date?)`: 특정 날짜 또는 전체 전략 기록 조회
- `create_strategy(date, question?)`: RAG와 FitLog Diet Strategy Agent 기반 전략 생성

## Environment

```powershell
$env:FITLOG_MCP_USER_ID = "1"
$env:DATABASE_URL = "postgresql+psycopg://board:board@localhost:5432/board"
$env:OPENAI_API_KEY = "..."
```

`FITLOG_MCP_USER_ID`는 MCP tool이 조회할 FitLog 사용자 ID입니다. 현재 MCP 서버는 FastAPI HTTP 인증을 통하지 않고 백엔드 service layer를 직접 호출하므로 이 값이 필요합니다.

## Run

```powershell
cd backend
python -m app.mcp.server
```

MCP client 설정 예시:

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
        "DATABASE_URL": "postgresql+psycopg://board:board@localhost:5432/board"
      }
    }
  }
}
```

## Smoke Test

```powershell
cd backend
python -m app.mcp.smoke
```

