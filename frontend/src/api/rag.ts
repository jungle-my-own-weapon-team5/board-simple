import { apiRequest } from "./client";
import type { RagChatResponse } from "../types";

/**
 * 백엔드 RAG 채팅 API에 사용자 질문을 보내고 답변과 출처 목록을 받아옵니다.
 */
export function sendRagMessage(message: string) {
  return apiRequest<RagChatResponse>("/api/rag/chat", {
    method: "POST",
    json: { message }
  });
}
