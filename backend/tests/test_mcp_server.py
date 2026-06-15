from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.main import app
from app.services.mcp.registry import McpToolRegistry
from app.services.mcp.server import McpJsonRpcServer
from app.services.mcp.types import JsonObject, McpToolCallContext, McpToolDefinition

FRONTEND_ORIGIN = "http://localhost:3000"


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_settings() -> Settings:
        return Settings(
            app_env="test",
            mcp_server_enabled=True,
            mcp_allowed_tools="search_legal_documents,verify_citations",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_tools_list_returns_only_allowlisted_tools() -> None:
    server = _create_server(allowed_tool_names=["echo", "missing", "secret_tool"])

    response = server.handle(
        {"jsonrpc": "2.0", "id": "req-1", "method": "tools/list", "params": {}}
    )

    assert response["result"]["tools"] == [
        {
            "name": "echo",
            "description": "Echo test tool",
            "input_schema": {"type": "object"},
        },
        {
            "name": "secret_tool",
            "description": "Hidden test tool",
            "input_schema": {"type": "object"},
        },
    ]


def test_tools_call_executes_allowlisted_tool() -> None:
    server = _create_server(allowed_tool_names=["echo"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"query": "test"}},
        },
        context=McpToolCallContext(user_id=7),
    )

    assert response["result"] == {
        "tool_name": "echo",
        "arguments": {"query": "test"},
        "user_id": 7,
    }


def test_unknown_method_returns_json_rpc_error() -> None:
    server = _create_server(allowed_tool_names=["echo"])

    response = server.handle(
        {"jsonrpc": "2.0", "id": "req-3", "method": "unknown", "params": {}}
    )

    assert response["error"]["code"] == -32601
    assert response["error"]["data"]["error_code"] == "mcp_method_not_found"


def test_tools_call_rejects_not_allowlisted_tool() -> None:
    server = _create_server(allowed_tool_names=["echo"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "req-4",
            "method": "tools/call",
            "params": {"name": "secret_tool", "arguments": {}},
        }
    )

    assert response["error"]["code"] == -32602
    assert response["error"]["data"]["error_code"] == "mcp_tool_not_allowed"


def test_tools_call_rejects_invalid_arguments() -> None:
    server = _create_server(allowed_tool_names=["echo"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "req-5",
            "method": "tools/call",
            "params": {"name": "echo", "arguments": "not-object"},
        }
    )

    assert response["error"]["code"] == -32602
    assert response["error"]["data"]["error_code"] == "mcp_invalid_arguments"


def test_tool_exception_is_redacted() -> None:
    server = _create_server(allowed_tool_names=["explode"])

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "req-6",
            "method": "tools/call",
            "params": {"name": "explode", "arguments": {}},
        }
    )

    assert response["error"]["code"] == -32603
    assert response["error"]["data"]["error_code"] == "mcp_tool_execution_failed"
    assert "super-secret-value" not in str(response)


def test_mcp_endpoint_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": "req-7", "method": "tools/list", "params": {}},
        headers=_origin_headers(),
    )

    assert response.status_code == 401


def test_mcp_endpoint_lists_default_allowlisted_tools(client: TestClient) -> None:
    _register_and_login(client)

    response = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": "req-8", "method": "tools/list", "params": {}},
        headers=_origin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "req-8"
    assert [tool["name"] for tool in body["result"]["tools"]] == [
        "search_legal_documents",
        "verify_citations",
    ]


def _create_server(allowed_tool_names: list[str]) -> McpJsonRpcServer:
    registry = McpToolRegistry(
        [
            McpToolDefinition(
                name="echo",
                description="Echo test tool",
                input_schema={"type": "object"},
                handler=_echo_handler,
            ),
            McpToolDefinition(
                name="secret_tool",
                description="Hidden test tool",
                input_schema={"type": "object"},
                handler=_echo_handler,
            ),
            McpToolDefinition(
                name="explode",
                description="Exploding test tool",
                input_schema={"type": "object"},
                handler=_explode_handler,
            ),
        ]
    )
    return McpJsonRpcServer(
        registry=registry,
        allowed_tool_names=allowed_tool_names,
    )


def _echo_handler(
    arguments: JsonObject,
    context: McpToolCallContext,
) -> JsonObject:
    return {
        "tool_name": "echo",
        "arguments": arguments,
        "user_id": context.user_id,
    }


def _explode_handler(
    arguments: JsonObject,
    context: McpToolCallContext,
) -> JsonObject:
    raise RuntimeError("super-secret-value")


def _origin_headers(origin: str = FRONTEND_ORIGIN) -> dict[str, str]:
    return {"Origin": origin}


def _register_and_login(client: TestClient) -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "mcp-user@example.com",
            "password": "password123",
            "nickname": "mcp-user",
        },
        headers=_origin_headers(),
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"email": "mcp-user@example.com", "password": "password123"},
        headers=_origin_headers(),
    )
    assert login_response.status_code == 200
