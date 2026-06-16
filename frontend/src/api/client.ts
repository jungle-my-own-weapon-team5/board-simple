const CONFIGURED_API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function getApiBaseUrl() {
  if (typeof window === "undefined") {
    return CONFIGURED_API_BASE_URL;
  }

  const pageHostname = window.location.hostname;
  const isLocalPage = pageHostname === "localhost" || pageHostname === "127.0.0.1";

  try {
    const configuredUrl = new URL(CONFIGURED_API_BASE_URL);
    const isLocalApi =
      configuredUrl.hostname === "localhost" || configuredUrl.hostname === "127.0.0.1";
    if (isLocalPage && isLocalApi) {
      configuredUrl.hostname = pageHostname;
      return configuredUrl.toString().replace(/\/$/, "");
    }
  } catch {
    // Fall through to the configured value when it is not an absolute URL.
  }

  return CONFIGURED_API_BASE_URL;
}

export function getAssetUrl(pathOrUrl: string) {
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }
  return `${getApiBaseUrl()}${pathOrUrl}`;
}

type RequestOptions = RequestInit & {
  json?: unknown;
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

  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...options,
      headers,
      credentials: "include",
      body: options.json !== undefined ? JSON.stringify(options.json) : options.body
    });
  } catch {
    throw new ApiError(
      0,
      "API 서버에 연결하지 못했습니다. 백엔드 서버가 실행 중인지, 프론트와 백엔드 주소가 같은 localhost/127.0.0.1 조합인지 확인해 주세요."
    );
  }

  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail ?? message;
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
