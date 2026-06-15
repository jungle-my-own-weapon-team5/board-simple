#!/usr/bin/env node

import { createStrategy, getDailyMeals, getDailyReport, getStrategyHistory } from "./fitlogClient.js";

const protocolVersion = "2024-11-05";

const tools = [
  {
    name: "get_daily_meals",
    description: "특정 날짜의 FitLog 식단 기록을 조회합니다. 아침, 점심, 저녁, 간식과 음식별 영양값을 반환합니다.",
    inputSchema: {
      type: "object",
      properties: {
        date: { type: "string", description: "조회할 날짜입니다. YYYY-MM-DD 형식입니다." },
      },
      required: ["date"],
      additionalProperties: false,
    },
  },
  {
    name: "get_daily_report",
    description: "특정 날짜의 하루 영양 리포트를 조회합니다. 총 칼로리, 탄단지 합계, 목표 대비 상태, 경고를 반환합니다.",
    inputSchema: {
      type: "object",
      properties: {
        date: { type: "string", description: "조회할 날짜입니다. YYYY-MM-DD 형식입니다." },
      },
      required: ["date"],
      additionalProperties: false,
    },
  },
  {
    name: "get_strategy_history",
    description: "특정 날짜에 생성된 FitLog 전략 기록을 조회합니다. date를 생략하면 전체 전략 기록을 조회합니다.",
    inputSchema: {
      type: "object",
      properties: {
        date: { type: "string", description: "조회할 날짜입니다. YYYY-MM-DD 형식입니다." },
      },
      additionalProperties: false,
    },
  },
  {
    name: "create_strategy",
    description: "현재 목표, 식단 기록, 하루 리포트, RAG 근거를 바탕으로 새 식단 전략을 생성합니다.",
    inputSchema: {
      type: "object",
      properties: {
        date: { type: "string", description: "전략을 생성할 날짜입니다. YYYY-MM-DD 형식입니다." },
        question: { type: "string", description: "전략 생성에 참고할 사용자 질문입니다." },
      },
      required: ["date"],
      additionalProperties: false,
    },
  },
];

const handlers = {
  get_daily_meals: getDailyMeals,
  get_daily_report: getDailyReport,
  get_strategy_history: getStrategyHistory,
  create_strategy: createStrategy,
};

let buffer = Buffer.alloc(0);

function writeMessage(message) {
  const body = Buffer.from(JSON.stringify(message), "utf8");
  process.stdout.write(`Content-Length: ${body.length}\r\n\r\n`);
  process.stdout.write(body);
}

function result(id, resultValue) {
  writeMessage({ jsonrpc: "2.0", id, result: resultValue });
}

function error(id, code, message, data) {
  writeMessage({ jsonrpc: "2.0", id, error: { code, message, ...(data ? { data } : {}) } });
}

function contentJson(value) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(value, null, 2),
      },
    ],
  };
}

function validateDate(value, fieldName = "date") {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`${fieldName} must be a YYYY-MM-DD string`);
  }
}

async function handleRequest(message) {
  const { id, method, params = {} } = message;
  if (!method) return;
  if (id === undefined && method.startsWith("notifications/")) return;

  try {
    if (method === "initialize") {
      result(id, {
        protocolVersion,
        capabilities: { tools: {} },
        serverInfo: { name: "fitlog-context-mcp", version: "0.1.0" },
      });
      return;
    }
    if (method === "ping") {
      result(id, {});
      return;
    }
    if (method === "tools/list") {
      result(id, { tools });
      return;
    }
    if (method === "tools/call") {
      const name = params.name;
      const args = params.arguments || {};
      const handler = handlers[name];
      if (!handler) {
        error(id, -32602, `Unknown tool: ${name}`);
        return;
      }
      if (name !== "get_strategy_history" || args.date !== undefined) {
        validateDate(args.date);
      }
      if (args.question !== undefined && args.question !== null && typeof args.question !== "string") {
        throw new Error("question must be a string");
      }
      const value = await handler(args);
      result(id, contentJson(value));
      return;
    }
    error(id, -32601, `Method not found: ${method}`);
  } catch (err) {
    error(id, -32000, err instanceof Error ? err.message : "Tool execution failed");
  }
}

function tryReadHeaderMessage() {
  const headerEnd = buffer.indexOf("\r\n\r\n");
  if (headerEnd === -1) return null;
  const header = buffer.subarray(0, headerEnd).toString("utf8");
  const lengthLine = header.split("\r\n").find((line) => line.toLowerCase().startsWith("content-length:"));
  if (!lengthLine) {
    throw new Error("Missing Content-Length header");
  }
  const length = Number(lengthLine.split(":")[1].trim());
  const bodyStart = headerEnd + 4;
  const bodyEnd = bodyStart + length;
  if (buffer.length < bodyEnd) return null;
  const body = buffer.subarray(bodyStart, bodyEnd).toString("utf8");
  buffer = buffer.subarray(bodyEnd);
  return JSON.parse(body);
}

function tryReadLineMessage() {
  const newline = buffer.indexOf("\n");
  if (newline === -1) return null;
  const line = buffer.subarray(0, newline).toString("utf8").trim();
  buffer = buffer.subarray(newline + 1);
  if (!line) return null;
  return JSON.parse(line);
}

process.stdin.on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  try {
    while (buffer.length > 0) {
      const message = buffer.toString("utf8", 0, Math.min(buffer.length, 32)).startsWith("Content-Length:")
        ? tryReadHeaderMessage()
        : tryReadLineMessage();
      if (message === null) break;
      void handleRequest(message);
    }
  } catch (err) {
    error(null, -32700, err instanceof Error ? err.message : "Parse error");
    buffer = Buffer.alloc(0);
  }
});

process.stdin.resume();
