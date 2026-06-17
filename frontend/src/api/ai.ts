import { apiRequest, streamNdjson } from "./client";
import type {
  AgentChatPageContext,
  AgentRunResponse,
  DiscussionTopic,
  EditorAgentHistoryMessage,
  EditorAgentResponse,
  ExternalSearchResponse,
  RagCorpusMode,
  RagQualityAgentResponse,
  RagSearchResponse
} from "../types";

const DISCUSSION_TOPICS_CACHE_TTL_MS = 60_000;

export type EditorAgentPayload = {
  title: string;
  content: string;
  post_type: string;
  category: string;
  message: string;
  history?: EditorAgentHistoryMessage[];
};

export type EditorAgentStreamEvent =
  | {
      type: "progress";
      step: string;
      label: string;
      percent: number;
    }
  | {
      type: "done";
      response: EditorAgentResponse;
    };

export function listDiscussionTopics() {
  return apiRequest<DiscussionTopic[]>("/api/ai/topics", {
    cacheTtlMs: DISCUSSION_TOPICS_CACHE_TTL_MS,
  });
}

export function runEditorAgent(payload: EditorAgentPayload) {
  return apiRequest<EditorAgentResponse>("/api/ai/editor-agent/run", {
    method: "POST",
    json: payload
  });
}

export function streamEditorAgent(
  payload: EditorAgentPayload,
  onEvent: (event: EditorAgentStreamEvent) => void
) {
  return streamNdjson<EditorAgentStreamEvent>("/api/ai/editor-agent/stream", {
    method: "POST",
    json: payload,
    onEvent
  });
}

export function searchRag(payload: { query: string; top_k: number; corpus?: RagCorpusMode }) {
  return apiRequest<RagSearchResponse>("/api/ai/rag/search", {
    method: "POST",
    json: payload
  });
}

export function searchRagWithAgent(payload: { query: string; top_k: number; corpus?: RagCorpusMode }) {
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

export function chatAgent(
  payload: { message: string; page_context?: AgentChatPageContext },
  options: { signal?: AbortSignal } = {}
) {
  return apiRequest<AgentRunResponse>("/api/ai/agent/chat", {
    method: "POST",
    json: payload,
    signal: options.signal
  });
}
