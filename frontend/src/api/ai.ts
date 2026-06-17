import { apiRequest } from "./client";
import type {
  AnswerDraftRequest,
  AnswerDraftResponse,
  DisputeIssuesRequest,
  DisputeIssuesResponse,
  FullAnalysisRequest,
  FullAnalysisResponse
} from "../types";

// 쟁점 정리와 답변 초안은 모두 backend Orchestrator Agent를 통해 실행합니다.
export function createDisputeIssues(payload: DisputeIssuesRequest) {
  return apiRequest<DisputeIssuesResponse>("/api/ai/dispute-issues", {
    method: "POST",
    json: payload
  });
}

export function createAnswerDraft(payload: AnswerDraftRequest) {
  return apiRequest<AnswerDraftResponse>("/api/ai/answer-drafts", {
    method: "POST",
    json: payload
  });
}

export function createFullAnalysis(payload: FullAnalysisRequest) {
  return apiRequest<FullAnalysisResponse>("/api/ai/full-analysis", {
    method: "POST",
    json: payload
  });
}
