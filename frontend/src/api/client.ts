const CONFIGURED_API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function getApiBaseUrl() {
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
  cacheTtlMs?: number;
  cacheKey?: string;
  invalidateCache?: boolean | string[];
};

type ApiCacheEntry = {
  expiresAt: number;
  value: unknown;
};

const apiCache = new Map<string, ApiCacheEntry>();
const inFlightGetRequests = new Map<string, Promise<unknown>>();

function cacheKeyFor(path: string, options: RequestOptions) {
  return options.cacheKey ?? path;
}

export function clearApiCache(prefix?: string) {
  if (!prefix) {
    apiCache.clear();
    inFlightGetRequests.clear();
    return;
  }
  for (const key of apiCache.keys()) {
    if (key.startsWith(prefix)) {
      apiCache.delete(key);
    }
  }
  for (const key of inFlightGetRequests.keys()) {
    if (key.startsWith(prefix)) {
      inFlightGetRequests.delete(key);
    }
  }
}

function invalidateAfterMutation(setting: RequestOptions["invalidateCache"]) {
  if (setting === false) {
    return;
  }
  if (Array.isArray(setting)) {
    for (const prefix of setting) {
      clearApiCache(prefix);
    }
    return;
  }
  clearApiCache();
}

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
  const method = (options.method ?? "GET").toUpperCase();
  const shouldCache = method === "GET" && Boolean(options.cacheTtlMs);
  const requestCacheKey = cacheKeyFor(path, options);

  if (shouldCache) {
    const cached = apiCache.get(requestCacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value as T;
    }

    const inFlight = inFlightGetRequests.get(requestCacheKey);
    if (inFlight) {
      return inFlight as Promise<T>;
    }
  }

  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const requestPromise = fetch(`${getApiBaseUrl()}${path}`, {
    ...options,
    headers,
    credentials: "include",
    body: options.json !== undefined ? JSON.stringify(options.json) : options.body
  })
    .then(async (response) => {
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
        if (method !== "GET") {
          invalidateAfterMutation(options.invalidateCache);
        }
        return undefined as T;
      }

      const value = await response.json() as T;
      if (shouldCache) {
        apiCache.set(requestCacheKey, {
          expiresAt: Date.now() + (options.cacheTtlMs ?? 0),
          value,
        });
      }
      if (method !== "GET") {
        invalidateAfterMutation(options.invalidateCache);
      }
      return value;
    })
    .catch((error) => {
      if (error instanceof ApiError || error instanceof DOMException && error.name === "AbortError") {
        throw error;
      }
      throw new ApiError(
        0,
        "API 서버에 연결하지 못했습니다. 백엔드 서버가 실행 중인지, 프론트와 백엔드 주소가 같은 localhost/127.0.0.1 조합인지 확인해 주세요."
      );
    })
    .finally(() => {
      if (shouldCache) {
        inFlightGetRequests.delete(requestCacheKey);
      }
    });

  if (shouldCache) {
    inFlightGetRequests.set(requestCacheKey, requestPromise);
  }

  return requestPromise;
}

export async function uncachedApiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  return apiRequest<T>(path, { ...options, cacheTtlMs: undefined });
}

export async function streamNdjson<T>(
  path: string,
  options: RequestOptions & {
    onEvent: (event: T) => void;
  }
): Promise<void> {
  const { onEvent, ...requestOptions } = options;
  const headers = new Headers(options.headers);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...requestOptions,
    headers,
    credentials: "include",
    body: options.json !== undefined ? JSON.stringify(options.json) : options.body
  });

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

  if (!response.body) {
    throw new ApiError(0, "스트리밍 응답을 읽을 수 없습니다.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed) {
        onEvent(JSON.parse(trimmed) as T);
      }
    }
    if (done) {
      break;
    }
  }

  const trimmed = buffer.trim();
  if (trimmed) {
    onEvent(JSON.parse(trimmed) as T);
  }
}
