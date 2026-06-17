from __future__ import annotations

import json
import subprocess
import sys


def frame(message: dict[str, object]) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def main() -> int:
    process = subprocess.run(
        [sys.executable, "-m", "app.mcp.server"],
        input=b"".join(
            [
                frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            ]
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = process.stdout.decode("utf-8", errors="replace")
    if process.returncode != 0:
        sys.stderr.write(process.stderr.decode("utf-8", errors="replace"))
        return process.returncode
    if "fitlog-context-mcp" not in output or "get_daily_meals" not in output or "create_strategy" not in output:
        sys.stderr.write(output)
        return 1
    print("Python MCP smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

