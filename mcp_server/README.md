# Deprecated Node MCP Server

이 폴더의 Node MCP 서버는 초기 구현입니다.

현재 기준 MCP 구현은 Python 백엔드 내부로 이동했습니다.

새 구현 위치:

```text
backend/app/mcp/server.py
backend/app/mcp/tools.py
backend/app/mcp/README.md
```

새 실행 방법:

```powershell
cd backend
python -m app.mcp.server
```

새 smoke test:

```powershell
cd backend
python -m app.mcp.smoke
```

이 Node 구현은 참고용으로만 남겨둡니다.

