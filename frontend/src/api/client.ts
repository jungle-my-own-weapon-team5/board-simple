const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type RequestOptions = RequestInit & {
  json?: unknown;
};

const BACKEND_ERROR_MESSAGES: Record<string, string> = {
  "AI/RAG API is disabled":
    "AI/RAG 기능이 비활성화되어 있습니다. 백엔드 설정을 확인하세요.",
  "No active embedding profile is available":
    "검색에 사용할 임베딩 프로필이 없습니다. 법률 문서 색인을 먼저 실행하세요."
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
    body: options.json !== undefined ? JSON.stringify(options.json) : options.body
  });

  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = errorMessageFromPayload(payload, message);
    } catch {
      // Keep the response status text when the server does not send JSON.
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function errorMessageFromPayload(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) {
    return fallback;
  }
  return errorMessageFromDetail(payload.detail, fallback);
}

function errorMessageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") {
    return translateBackendMessage(detail);
  }

  if (Array.isArray(detail)) {
    const validationMessages = detail
      .map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const msg = item.msg;
        const loc = item.loc;
        if (typeof msg !== "string") {
          return null;
        }
        if (Array.isArray(loc)) {
          return `${loc.join(".")}: ${msg}`;
        }
        return msg;
      })
      .filter((message): message is string => Boolean(message));
    return validationMessages.length > 0 ? validationMessages.join("\n") : fallback;
  }

  if (isRecord(detail)) {
    const message = stringValue(detail.message);
    const errorCode = stringValue(detail.error_code);
    if (message !== null) {
      return translateBackendMessage(message);
    }
    if (errorCode !== null) {
      return translateBackendMessage(errorCode);
    }
    return fallback;
  }

  return fallback;
}

function translateBackendMessage(message: string): string {
  return BACKEND_ERROR_MESSAGES[message] ?? message;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
