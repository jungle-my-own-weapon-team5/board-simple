import { apiRequest } from "./client";
import type { User } from "../types";

export function register(payload: {
  email: string;
  password: string;
  nickname?: string;
}) {
  return apiRequest<User>("/api/auth/register", {
    method: "POST",
    json: payload
  });
}

export function login(payload: { email: string; password: string }) {
  return apiRequest<User>("/api/auth/login", {
    method: "POST",
    json: payload
  });
}

export function logout() {
  return apiRequest<void>("/api/auth/logout", { method: "POST" });
}

export function getMe() {
  return apiRequest<User>("/api/auth/me");
}
