"use client";

import { Loader2, MessageCircle, Send, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useRef, useState } from "react";

import { sendRagMessage } from "@/api/rag";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { RagChatSource } from "@/types";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: RagChatSource[];
};

function sourceHref(source: RagChatSource) {
  return source.anchor ? `/posts/${source.post_id}#${source.anchor}` : `/posts/${source.post_id}`;
}

export default function FloatingChat() {
  const [isOpen, setIsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      role: "assistant",
      content: "게시글 내용에 대해 질문해보세요.",
    },
  ]);
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const nextId = useRef(2);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isSending) {
      return;
    }

    const userMessage: ChatMessage = {
      id: nextId.current++,
      role: "user",
      content: message,
    };

    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setError(null);
    setIsSending(true);

    try {
      const response = await sendRagMessage(message);
      setMessages((current) => [
        ...current,
        {
          id: nextId.current++,
          role: "assistant",
          content: response.answer,
          sources: response.sources,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "답변을 생성하지 못했습니다.");
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 flex max-w-[calc(100vw-2rem)] flex-col items-end gap-3">
      {isOpen ? (
        <section className="flex h-[34rem] max-h-[calc(100vh-7rem)] w-[23rem] max-w-full flex-col overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-xl">
          <header className="flex items-center justify-between border-b border-border px-4 py-3">
            <div>
              <h2 className="text-sm font-extrabold">게시글 AI 검색</h2>
              <p className="text-xs text-muted-foreground">RAG 기반 답변</p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="채팅 닫기"
              onClick={() => setIsOpen(false)}
            >
              <X />
            </Button>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {messages.map((message) => (
              <div
                key={message.id}
                className={
                  message.role === "user"
                    ? "ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                    : "mr-auto max-w-[90%] rounded-lg bg-muted px-3 py-2 text-sm"
                }
              >
                <p className="whitespace-pre-wrap break-words">{message.content}</p>
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
            ))}
            {isSending ? (
              <div className="mr-auto flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                답변 생성 중
              </div>
            ) : null}
          </div>

          {error ? (
            <p className="border-t border-border px-4 py-2 text-sm font-semibold text-destructive">
              {error}
            </p>
          ) : null}

          <form className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 border-t border-border p-3" onSubmit={handleSubmit}>
            <Textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="질문을 입력하세요"
              rows={2}
              className="min-h-12 resize-none"
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <Button type="submit" size="icon" aria-label="질문 보내기" disabled={isSending || !draft.trim()}>
              {isSending ? <Loader2 className="animate-spin" /> : <Send />}
            </Button>
          </form>
        </section>
      ) : null}

      <Button
        type="button"
        size="icon"
        className="h-12 w-12 rounded-full shadow-lg"
        aria-label={isOpen ? "채팅 닫기" : "채팅 열기"}
        onClick={() => setIsOpen((current) => !current)}
      >
        {isOpen ? <X /> : <MessageCircle />}
      </Button>
    </div>
  );
}
