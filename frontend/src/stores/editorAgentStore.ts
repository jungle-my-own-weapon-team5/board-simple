import { create } from "zustand";
import type { AgentChatContext } from "@/types";

export type AgentDraft = {
  title: string;
  content: string;
  tags: string[];
};

type EditorAgentState = {
  applyDraft: ((draft: AgentDraft) => void) | null;
  context: AgentChatContext | null;
  setApplyDraft: (handler: (draft: AgentDraft) => void) => void;
  clearApplyDraft: (handler: (draft: AgentDraft) => void) => void;
  setContext: (context: AgentChatContext) => void;
  clearContext: () => void;
};

export const useEditorAgentStore = create<EditorAgentState>((set, get) => ({
  applyDraft: null,
  context: null,
  setApplyDraft: (handler) => set({ applyDraft: handler }),
  clearApplyDraft: (handler) => {
    if (get().applyDraft === handler) {
      set({ applyDraft: null });
    }
  },
  setContext: (context) => set({ context }),
  clearContext: () => set({ context: null }),
}));
