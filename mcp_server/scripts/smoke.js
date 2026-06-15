import { spawn } from "node:child_process";
import { once } from "node:events";

function frame(message) {
  const body = Buffer.from(JSON.stringify(message), "utf8");
  return `Content-Length: ${body.length}\r\n\r\n${body}`;
}

const child = spawn(process.execPath, ["src/index.js"], { cwd: new URL("..", import.meta.url), stdio: ["pipe", "pipe", "inherit"] });
let output = "";
child.stdout.on("data", (chunk) => {
  output += chunk.toString("utf8");
});

child.stdin.write(frame({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }));
child.stdin.write(frame({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }));
child.stdin.end();

await once(child, "exit");

if (!output.includes("fitlog-context-mcp") || !output.includes("get_daily_meals") || !output.includes("create_strategy")) {
  console.error(output);
  process.exit(1);
}

console.log("MCP smoke test passed");
