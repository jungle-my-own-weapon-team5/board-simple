from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from app.core.database import get_session_local
from app.mcp.tools import TOOL_HANDLERS


PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "get_daily_meals",
        "description": "특정 날짜의 FitLog 식단 기록과 음식별 영양성분을 조회합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "조회 날짜입니다. YYYY-MM-DD 형식입니다."},
            },
            "required": ["date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_daily_report",
        "description": "특정 날짜의 하루 영양 리포트를 조회합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "조회 날짜입니다. YYYY-MM-DD 형식입니다."},
            },
            "required": ["date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_strategy_history",
        "description": "특정 날짜 또는 전체 FitLog 전략 기록을 조회합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "조회 날짜입니다. YYYY-MM-DD 형식입니다."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "create_strategy",
        "description": "목표, 식단 기록, 하루 리포트, RAG 근거를 바탕으로 식단 전략을 생성합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "전략을 생성할 날짜입니다. YYYY-MM-DD 형식입니다."},
                "question": {"type": "string", "description": "전략 생성에 반영할 사용자 질문입니다."},
            },
            "required": ["date"],
            "additionalProperties": False,
        },
    },
]


def write_message(message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def result(message_id: Any, value: Any) -> None:
    write_message({"jsonrpc": "2.0", "id": message_id, "result": value})


def error(message_id: Any, code: int, message: str, data: Any | None = None) -> None:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    write_message({"jsonrpc": "2.0", "id": message_id, "error": payload})


def content_json(value: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, ensure_ascii=False, indent=2),
            }
        ]
    }


def handle_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    session_local = get_session_local()
    db = session_local()
    try:
        return handler(db, args)
    finally:
        db.close()


def handle_request(message: dict[str, Any]) -> None:
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if not method:
        return
    if message_id is None and method.startswith("notifications/"):
        return

    try:
        if method == "initialize":
            result(
                message_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fitlog-context-mcp", "version": "0.2.0"},
                },
            )
            return
        if method == "ping":
            result(message_id, {})
            return
        if method == "tools/list":
            result(message_id, {"tools": TOOLS})
            return
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if not isinstance(name, str):
                raise ValueError("Tool name is required")
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be an object")
            result(message_id, content_json(handle_tool_call(name, args)))
            return
        error(message_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        error(message_id, -32000, str(exc))


def read_content_length_message(buffer: bytearray) -> dict[str, Any] | None:
    header_end = buffer.find(b"\r\n\r\n")
    if header_end == -1:
        return None
    header = bytes(buffer[:header_end]).decode("utf-8")
    length_line = next((line for line in header.split("\r\n") if line.lower().startswith("content-length:")), None)
    if length_line is None:
        raise ValueError("Missing Content-Length header")
    length = int(length_line.split(":", 1)[1].strip())
    body_start = header_end + 4
    body_end = body_start + length
    if len(buffer) < body_end:
        return None
    body = bytes(buffer[body_start:body_end]).decode("utf-8")
    del buffer[:body_end]
    return json.loads(body)


def read_line_message(buffer: bytearray) -> dict[str, Any] | None:
    newline = buffer.find(b"\n")
    if newline == -1:
        return None
    line = bytes(buffer[:newline]).decode("utf-8").strip()
    del buffer[: newline + 1]
    if not line:
        return None
    return json.loads(line)


def serve(read_chunk: Callable[[], bytes] | None = None) -> None:
    reader = read_chunk or (lambda: sys.stdin.buffer.read(4096))
    buffer = bytearray()
    while True:
        chunk = reader()
        if not chunk:
            break
        buffer.extend(chunk)
        try:
            while buffer:
                if bytes(buffer[:32]).startswith(b"Content-Length:"):
                    message = read_content_length_message(buffer)
                else:
                    message = read_line_message(buffer)
                if message is None:
                    break
                handle_request(message)
        except Exception as exc:
            error(None, -32700, str(exc))
            buffer.clear()


if __name__ == "__main__":
    serve()

