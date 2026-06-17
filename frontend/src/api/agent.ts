import { apiRequest } from "./client";
import type { AgentChatContext, AgentChatResponse, AgentPendingAction } from "../types";

export function sendAgentMessage(
  message: string,
  confirmAction?: AgentPendingAction,
  context?: AgentChatContext
) {
  return apiRequest<AgentChatResponse>("/api/agent/chat", {
    method: "POST",
    json: {
      message,
      confirm_action: confirmAction ?? null,
      context: context ?? null,
    },
  });
}
