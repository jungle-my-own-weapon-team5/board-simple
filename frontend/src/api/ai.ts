import { apiRequest } from "./client";
import type {
  AgentRunResponse,
  DiscussionTopic,
  ExternalSearchResponse,
  RagSearchResponse,
  WritingAssist
} from "../types";

export function listDiscussionTopics() {
  return apiRequest<DiscussionTopic[]>("/api/ai/topics");
}

export function getWritingAssist(payload: { title: string; content: string; post_type: string }) {
  return apiRequest<WritingAssist>("/api/ai/writing-assist", {
    method: "POST",
    json: payload
  });
}

export function searchRag(payload: { query: string; top_k: number }) {
  return apiRequest<RagSearchResponse>("/api/ai/rag/search", {
    method: "POST",
    json: payload
  });
}

export function searchExternal(payload: { keyword: string }) {
  return apiRequest<ExternalSearchResponse>("/api/ai/external/search", {
    method: "POST",
    json: payload
  });
}

export function runAgent(payload: { goal: string; topic: string }) {
  return apiRequest<AgentRunResponse>("/api/ai/agent/run", {
    method: "POST",
    json: payload
  });
}
