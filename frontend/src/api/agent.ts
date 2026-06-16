import { apiRequest } from "./client";
import type { AgentChatResponse, AgentPendingAction } from "../types";

export function sendAgentMessage(
  message: string,
  confirmAction?: AgentPendingAction
) {
  return apiRequest<AgentChatResponse>("/api/agent/chat", {
    method: "POST",
    json: {
      message,
      confirm_action: confirmAction ?? null,
    },
  });
}
