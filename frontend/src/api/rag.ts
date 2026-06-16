import { apiRequest } from "./client";
import type { RagSearchRequest, RagSearchResponse } from "../types";

// 답변 생성 없이 backend RAG retrieval 결과만 확인하는 API입니다.
export function searchRagDocuments(payload: RagSearchRequest) {
  return apiRequest<RagSearchResponse>("/api/rag/search", {
    method: "POST",
    json: payload
  });
}
