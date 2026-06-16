"use client";

import { Bot, Loader2, LogIn, MessageCircle, Send, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import * as aiApi from "@/api/ai";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/authStore";
import type { AgentRunResponse } from "@/types";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps?: AgentRunResponse["steps"];
  isError?: boolean;
};

function chatErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "로그인 후 AI 챗봇을 사용할 수 있습니다.";
    }
    return error.message;
  }
  return "챗봇 응답을 가져오지 못했습니다.";
}

export default function AiChatWidget() {
  const pathname = usePathname();
  const { user } = useAuthStore();
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isSubmitting]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || !user || isSubmitting) {
      return;
    }

    setInput("");
    setIsSubmitting(true);
    setMessages((current) => [
      ...current,
      { id: `${Date.now()}-user`, role: "user", content: message },
    ]);

    try {
      const response = await aiApi.chatAgent({
        message,
        page_context: { path: pathname ?? "/" },
      });
      setMessages((current) => [
        ...current,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: response.final_answer,
          steps: response.steps,
        },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `${Date.now()}-assistant-error`,
          role: "assistant",
          content: chatErrorMessage(error),
          isError: true,
        },
      ]);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-3 sm:bottom-6 sm:right-6">
      {isOpen ? (
        <section
          aria-label="AI 챗봇"
          className="flex h-[min(620px,calc(100vh-7rem))] w-[calc(100vw-2rem)] max-w-sm flex-col overflow-hidden rounded-md border border-border bg-card shadow-xl"
        >
          <header className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <Bot className="size-5 shrink-0" />
              <div className="min-w-0">
                <h2 className="truncate text-sm font-extrabold">AI 챗봇</h2>
                <p className="truncate text-xs text-muted-foreground">RAG 근거와 외부 자료 흐름으로 답변합니다.</p>
              </div>
            </div>
            <Button type="button" variant="ghost" size="icon" onClick={() => setIsOpen(false)} aria-label="챗봇 닫기">
              <X />
            </Button>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {!user ? (
              <div className="flex h-full flex-col items-start justify-center gap-3 text-sm">
                <p className="font-semibold">로그인 후 AI 챗봇을 사용할 수 있습니다.</p>
                <p className="text-muted-foreground">대화형 AI 호출은 사용자 세션이 확인될 때만 실행합니다.</p>
                <Button asChild size="sm">
                  <Link href="/login">
                    <LogIn />
                    <span>Login</span>
                  </Link>
                </Button>
              </div>
            ) : messages.length === 0 ? (
              <div className="flex h-full flex-col justify-center gap-2 text-sm text-muted-foreground">
                <p className="font-semibold text-foreground">역사 글쓰기와 자료 확인을 도와드립니다.</p>
                <p>현재 화면 맥락을 함께 보내고, 내부 RAG와 외부 자료 링크를 활용해 답변합니다.</p>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {messages.map((message) => (
                  <article
                    key={message.id}
                    className={cn(
                      "max-w-[88%] rounded-md border px-3 py-2 text-sm leading-6",
                      message.role === "user"
                        ? "ml-auto border-primary bg-primary text-primary-foreground"
                        : "mr-auto border-border bg-background",
                      message.isError ? "border-destructive text-destructive" : null
                    )}
                  >
                    <p className="whitespace-pre-wrap break-words">{message.content}</p>
                    {message.steps?.length ? (
                      <details className="mt-2 border-t border-border pt-2 text-xs">
                        <summary className="cursor-pointer font-semibold">실행 로그</summary>
                        <div className="mt-2 flex flex-col gap-1 text-muted-foreground">
                          {message.steps.map((step) => (
                            <p key={`${message.id}-${step.name}`}>
                              <span className="font-semibold text-foreground">{step.name}</span>
                              {" · "}
                              {step.output}
                            </p>
                          ))}
                        </div>
                      </details>
                    ) : null}
                  </article>
                ))}
                {isSubmitting ? (
                  <div className="mr-auto flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    <span>응답 생성 중</span>
                  </div>
                ) : null}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          <form className="border-t border-border p-3" onSubmit={handleSubmit}>
            <div className="flex items-end gap-2">
              <Textarea
                className="max-h-28 min-h-10 resize-none"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder={user ? "역사 자료나 글쓰기 질문을 입력하세요" : "로그인이 필요합니다"}
                disabled={!user || isSubmitting}
              />
              <Button type="submit" size="icon" disabled={!user || !input.trim() || isSubmitting} aria-label="메시지 보내기">
                {isSubmitting ? <Loader2 className="animate-spin" /> : <Send />}
              </Button>
            </div>
          </form>
        </section>
      ) : null}

      <Button
        type="button"
        size="icon"
        className="h-12 w-12 rounded-full shadow-lg"
        onClick={() => setIsOpen((current) => !current)}
        aria-label={isOpen ? "챗봇 닫기" : "챗봇 열기"}
      >
        {isOpen ? <X /> : <MessageCircle />}
      </Button>
    </div>
  );
}
