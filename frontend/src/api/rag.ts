import { apiRequest } from "./client";
import type { RagAskResponse } from "../types";

export function askRag(payload: { question: string }) {
  return apiRequest<RagAskResponse>("/api/rag/ask", {
    method: "POST",
    json: payload
  });
}
