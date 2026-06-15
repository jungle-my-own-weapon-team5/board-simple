import { apiRequest } from "./client";
import type { RagChatResponse } from "../types";

export function sendRagMessage(message: string) {
  return apiRequest<RagChatResponse>("/api/rag/chat", {
    method: "POST",
    json: { message }
  });
}
