const API_BASE_URL = process.env.FITLOG_API_BASE_URL || "http://localhost:8000";
const AUTH_COOKIE = process.env.FITLOG_AUTH_COOKIE || "";
const BEARER_TOKEN = process.env.FITLOG_BEARER_TOKEN || "";

function apiUrl(path) {
  return new URL(path, API_BASE_URL).toString();
}

function authHeaders() {
  const headers = { Accept: "application/json" };
  if (AUTH_COOKIE) {
    headers.Cookie = AUTH_COOKIE;
  }
  if (BEARER_TOKEN) {
    headers.Authorization = `Bearer ${BEARER_TOKEN}`;
  }
  return headers;
}

async function requestJson(path, options = {}) {
  const headers = {
    ...authHeaders(),
    ...(options.body ? { "Content-Type": "application/json" } : {}),
  };
  const response = await fetch(apiUrl(path), { ...options, headers });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null ? JSON.stringify(payload) : String(payload || "");
    throw new Error(`FitLog API ${response.status} ${response.statusText}: ${detail}`);
  }
  return payload;
}

export function getDailyMeals({ date }) {
  return requestJson(`/api/fitlog/meals?date=${encodeURIComponent(date)}`);
}

export function getDailyReport({ date }) {
  return requestJson(`/api/fitlog/reports/daily?date=${encodeURIComponent(date)}`);
}

export function getStrategyHistory({ date }) {
  const suffix = date ? `?date=${encodeURIComponent(date)}` : "";
  return requestJson(`/api/fitlog/strategy${suffix}`);
}

export function createStrategy({ date, question = null }) {
  return requestJson("/api/fitlog/strategy", {
    method: "POST",
    body: JSON.stringify({ date, question }),
  });
}
