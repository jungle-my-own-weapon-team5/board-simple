import { apiRequest } from "./client";
import type {
  AgentChatPageContext,
  AgentRunResponse,
  DiscussionTopic,
  ExternalSearchResponse,
  RagQualityAgentResponse,
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

export function searchRagWithAgent(payload: { query: string; top_k: number }) {
  return apiRequest<RagQualityAgentResponse>("/api/ai/rag/agent-search", {
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

export function chatAgent(payload: { message: string; page_context?: AgentChatPageContext }) {
  return apiRequest<AgentRunResponse>("/api/ai/agent/chat", {
    method: "POST",
    json: payload
  });
}
