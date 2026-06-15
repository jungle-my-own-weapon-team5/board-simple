# FitLog Context MCP

FitLog Context MCP는 외부 AI Agent가 기존 FastAPI FitLog API를 도구처럼 호출할 수 있게 하는 stdio MCP 서버입니다.

## Tools

- `get_daily_meals(date)`: 특정 날짜 식단 기록 조회
- `get_daily_report(date)`: 특정 날짜 하루 영양 리포트 조회
- `get_strategy_history(date?)`: 특정 날짜 또는 전체 전략 기록 조회
- `create_strategy(date, question?)`: 목표, 식단, 리포트, RAG 근거 기반 전략 생성

## Environment

```powershell
$env:FITLOG_API_BASE_URL = "http://localhost:8000"
$env:FITLOG_AUTH_COOKIE = "access_token=YOUR_LOGIN_COOKIE_VALUE"
```

`FITLOG_AUTH_COOKIE`는 기존 FastAPI의 HttpOnly 로그인 쿠키를 MCP 서버가 대신 보내기 위한 값입니다.
개발/시연용으로 적합한 방식이며, 실제 서비스에서는 사용자별 인증 연동을 별도로 설계해야 합니다.

## Run

```powershell
cd mcp_server
npm run start
```

MCP 클라이언트 설정 예시:

```json
{
  "mcpServers": {
    "fitlog-context": {
      "command": "node",
      "args": ["C:/crafton/1/ai_utilization/board_simple/mcp_server/src/index.js"],
      "env": {
        "FITLOG_API_BASE_URL": "http://localhost:8000",
        "FITLOG_AUTH_COOKIE": "access_token=YOUR_LOGIN_COOKIE_VALUE"
      }
    }
  }
}
```

## Smoke Test

```powershell
cd mcp_server
npm run smoke
```
