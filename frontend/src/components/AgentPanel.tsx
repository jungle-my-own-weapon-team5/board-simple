"use client";

import { Check, Loader2, Send, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useRef, useState } from "react";

import { sendAgentMessage } from "@/api/agent";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { AgentPendingAction, AgentSource } from "@/types";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: AgentSource[];
  pendingAction?: AgentPendingAction;
  createdPost?: {
    post_id: number;
    title: string;
  } | null;
};

type AgentPanelProps = {
  isAuthenticated: boolean;
  isOpen: boolean;
  onClose: () => void;
};

function sourceHref(source: AgentSource) {
  return source.anchor ? `/posts/${source.post_id}#${source.anchor}` : `/posts/${source.post_id}`;
}

export default function AgentPanel({ isAuthenticated, isOpen, onClose }: AgentPanelProps) {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      role: "assistant",
      content: "무엇을 도와드릴까요?",
    },
  ]);
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const nextId = useRef(2);

  if (!isOpen) {
    return null;
  }

  const appendAgentResponse = (response: Awaited<ReturnType<typeof sendAgentMessage>>) => {
    setMessages((current) => [
      ...current,
      {
        id: nextId.current++,
        role: "assistant",
        content: response.answer,
        sources: response.sources,
        pendingAction: response.pending_action ?? undefined,
        createdPost: response.created_post,
      },
    ]);
  };

  const clearPendingActions = (current: ChatMessage[]) =>
    current.map((message) =>
      message.pendingAction ? { ...message, pendingAction: undefined } : message,
    );

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isSending) {
      return;
    }

    setMessages((current) => [
      ...clearPendingActions(current),
      {
        id: nextId.current++,
        role: "user",
        content: message,
      },
    ]);
    setDraft("");
    setError(null);
    setIsSending(true);

    try {
      appendAgentResponse(await sendAgentMessage(message));
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI Agent 응답을 생성하지 못했습니다.");
    } finally {
      setIsSending(false);
    }
  };

  const handleConfirm = async (action: AgentPendingAction) => {
    if (isSending) {
      return;
    }

    setMessages((current) => [
      ...clearPendingActions(current),
      {
        id: nextId.current++,
        role: "user",
        content: "게시글 생성을 확인합니다.",
      },
    ]);
    setError(null);
    setIsSending(true);

    try {
      appendAgentResponse(await sendAgentMessage("confirm create_post", action));
    } catch (err) {
      setError(err instanceof Error ? err.message : "게시글을 생성하지 못했습니다.");
    } finally {
      setIsSending(false);
    }
  };

  const handleCancel = () => {
    setMessages((current) => [
      ...clearPendingActions(current),
      {
        id: nextId.current++,
        role: "assistant",
        content: "게시글 생성을 취소했습니다.",
      },
    ]);
  };

  return (
    <section className="fixed right-4 top-20 z-50 flex h-[34rem] max-h-[calc(100vh-6rem)] w-[24rem] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-xl">
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-extrabold">AI Agent</h2>
          <p className="text-xs text-muted-foreground">게시판 작업 도우미</p>
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="AI Agent 닫기" onClick={onClose}>
          <X />
        </Button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {isAuthenticated ? (
          messages.map((message) => (
            <div
              key={message.id}
              className={
                message.role === "user"
                  ? "ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                  : "mr-auto max-w-[90%] rounded-lg bg-muted px-3 py-2 text-sm"
              }
            >
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
              {message.pendingAction ? (
                <div className="mt-3 space-y-2 border-t border-border/70 pt-2">
                  <div className="rounded-md border border-border bg-background p-2 text-xs">
                    <p className="font-semibold">{message.pendingAction.title}</p>
                    <p className="mt-1 line-clamp-4 text-muted-foreground">
                      {message.pendingAction.content}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => void handleConfirm(message.pendingAction!)}
                      disabled={isSending}
                    >
                      <Check />
                      <span>Create post</span>
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={handleCancel}>
                      <X />
                      <span>Cancel</span>
                    </Button>
                  </div>
                </div>
              ) : null}
              {message.createdPost ? (
                <Link
                  href={`/posts/${message.createdPost.post_id}`}
                  className="mt-3 block rounded-md border border-border bg-background px-2 py-1.5 text-xs font-semibold hover:border-primary"
                >
                  {message.createdPost.title}
                </Link>
              ) : null}
              {message.sources && message.sources.length > 0 ? (
                <div className="mt-3 space-y-2 border-t border-border/70 pt-2">
                  {message.sources.map((source) => (
                    <Link
                      key={`${source.post_id}-${source.anchor ?? source.heading ?? source.title}`}
                      href={sourceHref(source)}
                      className="block rounded-md border border-border bg-background px-2 py-1.5 text-xs hover:border-primary"
                    >
                      <span className="block font-semibold">{source.title}</span>
                      {source.heading ? (
                        <span className="block text-muted-foreground">{source.heading}</span>
                      ) : null}
                      <span className="mt-1 line-clamp-2 block text-muted-foreground">
                        {source.snippet}
                      </span>
                    </Link>
                  ))}
                </div>
              ) : null}
            </div>
          ))
        ) : (
          <div className="rounded-lg bg-muted px-3 py-3 text-sm">
            <p className="font-semibold">로그인 후 AI Agent를 사용할 수 있습니다.</p>
            <p className="mt-1 text-muted-foreground">
              게시글 조회와 생성은 사용자 계정 권한으로 실행됩니다.
            </p>
            <div className="mt-3 flex gap-2">
              <Button asChild size="sm">
                <Link href="/login" onClick={onClose}>
                  Login
                </Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link href="/register" onClick={onClose}>
                  Register
                </Link>
              </Button>
            </div>
          </div>
        )}
        {isAuthenticated && isSending ? (
          <div className="mr-auto flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            처리 중
          </div>
        ) : null}
      </div>

      {isAuthenticated && error ? (
        <p className="border-t border-border px-4 py-2 text-sm font-semibold text-destructive">
          {error}
        </p>
      ) : null}

      {isAuthenticated ? (
        <form className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 border-t border-border p-3" onSubmit={handleSubmit}>
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="요청을 입력하세요"
            rows={2}
            className="min-h-12 resize-none"
            onKeyDown={(event) => {
              const isComposing = event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229;

              if (event.key === "Enter" && !event.shiftKey && !isComposing) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <Button type="submit" size="icon" aria-label="AI Agent 요청 보내기" disabled={isSending || !draft.trim()}>
            {isSending ? <Loader2 className="animate-spin" /> : <Send />}
          </Button>
        </form>
      ) : null}
    </section>
  );
}
