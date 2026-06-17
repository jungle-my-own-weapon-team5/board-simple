"use client";

import { Bot, GripHorizontal, GripVertical, Loader2, LogIn, Maximize2, MessageCircle, Minimize2, Send, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, PointerEvent, useEffect, useRef, useState } from "react";

import * as aiApi from "@/api/ai";
import { ApiError } from "@/api/client";
import MarkdownContent from "@/components/MarkdownContent";
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

type ChatSize = {
  width: number;
  height: number;
};

type ResizeEdge = "left" | "top" | "corner";

type ResizeState = {
  edge: ResizeEdge;
  startX: number;
  startY: number;
  startWidth: number;
  startHeight: number;
};

const DEFAULT_CHAT_SIZE: ChatSize = { width: 384, height: 620 };
const MIN_CHAT_SIZE: ChatSize = { width: 320, height: 420 };
const MAX_CHAT_SIZE: ChatSize = { width: 560, height: 760 };
const CHAT_VIEWPORT_MARGIN = 24;

function chatErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "로그인 후 AI 챗봇을 사용할 수 있습니다.";
    }
    return error.message;
  }
  return "챗봇 응답을 가져오지 못했습니다.";
}

function getViewportSize() {
  if (typeof window === "undefined") {
    return { width: 1280, height: 800 };
  }
  return { width: window.innerWidth, height: window.innerHeight };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getChatSizeLimits(viewport: { width: number; height: number }) {
  return {
    minWidth: Math.min(MIN_CHAT_SIZE.width, Math.max(0, viewport.width - CHAT_VIEWPORT_MARGIN * 2)),
    maxWidth: Math.max(
      MIN_CHAT_SIZE.width,
      Math.min(MAX_CHAT_SIZE.width, viewport.width - CHAT_VIEWPORT_MARGIN * 2)
    ),
    minHeight: Math.min(MIN_CHAT_SIZE.height, Math.max(0, viewport.height - 112)),
    maxHeight: Math.max(
      MIN_CHAT_SIZE.height,
      Math.min(MAX_CHAT_SIZE.height, viewport.height - 112)
    ),
  };
}

function normalizeChatSize(size: ChatSize, viewport: { width: number; height: number }) {
  const limits = getChatSizeLimits(viewport);
  return {
    width: clamp(size.width, limits.minWidth, limits.maxWidth),
    height: clamp(size.height, limits.minHeight, limits.maxHeight),
  };
}

export default function AiChatWidget() {
  const pathname = usePathname();
  const { user } = useAuthStore();
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [viewport, setViewport] = useState(getViewportSize);
  const [chatSize, setChatSize] = useState(DEFAULT_CHAT_SIZE);
  const resizeStateRef = useRef<ResizeState | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const normalizedSize = normalizeChatSize(chatSize, viewport);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isSubmitting]);

  useEffect(() => {
    const handleResize = () => {
      setViewport(getViewportSize());
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    setChatSize((current) => normalizeChatSize(current, viewport));
  }, [viewport]);

  useEffect(() => {
    const openChat = () => setIsOpen(true);
    window.addEventListener("history-board:open-ai-chat", openChat);
    return () => window.removeEventListener("history-board:open-ai-chat", openChat);
  }, []);

  const beginResize = (event: PointerEvent<HTMLButtonElement>, edge: ResizeEdge) => {
    event.preventDefault();
    resizeStateRef.current = {
      edge,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: normalizedSize.width,
      startHeight: normalizedSize.height,
    };

    const handlePointerMove = (moveEvent: globalThis.PointerEvent) => {
      const resizeState = resizeStateRef.current;
      if (!resizeState) {
        return;
      }
      const width = resizeState.edge === "left" || resizeState.edge === "corner"
        ? resizeState.startWidth + resizeState.startX - moveEvent.clientX
        : resizeState.startWidth;
      const height = resizeState.edge === "top" || resizeState.edge === "corner"
        ? resizeState.startHeight + resizeState.startY - moveEvent.clientY
        : resizeState.startHeight;
      setChatSize(normalizeChatSize({ width, height }, getViewportSize()));
    };

    const handlePointerUp = () => {
      resizeStateRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };

    const cursor = edge === "left" ? "ew-resize" : edge === "top" ? "ns-resize" : "nwse-resize";
    document.body.style.cursor = cursor;
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || !user || isSubmitting) {
      return;
    }

    setInput("");
    setIsSubmitting(true);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setMessages((current) => [
      ...current,
      { id: `${Date.now()}-user`, role: "user", content: message },
    ]);

    try {
      const response = await aiApi.chatAgent({
        message,
        page_context: { path: pathname ?? "/" },
      }, {
        signal: abortController.signal,
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
      if (error instanceof DOMException && error.name === "AbortError") {
        setMessages((current) => [
          ...current,
          {
            id: `${Date.now()}-assistant-aborted`,
            role: "assistant",
            content: "응답 생성을 중단했습니다.",
          },
        ]);
        return;
      }
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
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      setIsSubmitting(false);
    }
  };

  const handleStop = () => {
    abortControllerRef.current?.abort();
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-3 sm:bottom-6 sm:right-6">
      {isOpen ? (
        <section
          aria-label="AI 챗봇"
          className="relative flex max-h-[calc(100vh-7rem)] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-sm border border-border bg-card shadow-[0_22px_60px_-34px_rgba(28,27,27,0.65)]"
          style={{
            width: `${normalizedSize.width}px`,
            height: `${normalizedSize.height}px`,
          }}
        >
          <button
            type="button"
            className="absolute left-0 top-9 z-10 hidden h-[calc(100%-4.5rem)] w-2 cursor-ew-resize items-center justify-center text-muted-foreground hover:bg-accent/70 lg:flex"
            onPointerDown={(event) => beginResize(event, "left")}
            aria-label="챗봇 너비 조절"
            title="챗봇 너비 조절"
          >
            <GripVertical className="size-3" />
          </button>
          <button
            type="button"
            className="absolute left-9 top-0 z-10 hidden h-2 w-[calc(100%-4.5rem)] cursor-ns-resize items-center justify-center text-muted-foreground hover:bg-accent/70 lg:flex"
            onPointerDown={(event) => beginResize(event, "top")}
            aria-label="챗봇 높이 조절"
            title="챗봇 높이 조절"
          >
            <GripHorizontal className="size-3" />
          </button>
          <button
            type="button"
            className="absolute left-0 top-0 z-20 hidden size-7 cursor-nwse-resize items-center justify-center text-muted-foreground hover:bg-accent/70 lg:flex"
            onPointerDown={(event) => beginResize(event, "corner")}
            aria-label="챗봇 크기 조절"
            title="챗봇 크기 조절"
          >
            <Maximize2 className="size-3" />
          </button>
          <header className="flex items-center justify-between border-b border-border bg-background/70 px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <Bot className="size-5 shrink-0" />
              <div className="min-w-0">
                <h2 className="font-serif-display truncate text-base font-bold">AI 챗봇</h2>
                <p className="truncate text-xs text-muted-foreground">RAG 근거와 외부 자료 흐름으로 답변합니다.</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setChatSize(DEFAULT_CHAT_SIZE)}
                aria-label="챗봇 크기 초기화"
                title="챗봇 크기 초기화"
              >
                <Minimize2 />
              </Button>
              <Button type="button" variant="ghost" size="icon" onClick={() => setIsOpen(false)} aria-label="챗봇 닫기">
                <X />
              </Button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {!user ? (
              <div className="flex h-full flex-col items-start justify-center gap-3 text-sm">
                <p className="font-semibold">로그인 후 AI 챗봇을 사용할 수 있습니다.</p>
                <p className="text-muted-foreground">대화형 AI 호출은 사용자 세션이 확인될 때만 실행합니다.</p>
                <Button asChild size="sm" className="rounded-sm">
                  <Link href="/login">
                    <LogIn />
                    <span>로그인</span>
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
                      "max-w-[88%] rounded-sm border px-3 py-2 text-sm leading-6",
                      message.role === "user"
                        ? "ml-auto border-primary bg-primary text-primary-foreground"
                        : "mr-auto border-border bg-background",
                      message.isError ? "border-destructive text-destructive" : null
                    )}
                  >
                    {message.role === "assistant" ? (
                      <MarkdownContent value={message.content} className="chat-markdown break-words" />
                    ) : (
                      <p className="whitespace-pre-wrap break-words">{message.content}</p>
                    )}
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
                  <div className="mr-auto flex items-center gap-2 rounded-sm border border-border bg-background px-3 py-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                    <span>응답 생성 중</span>
                  </div>
                ) : null}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          <form className="border-t border-border bg-background/70 p-3" onSubmit={handleSubmit}>
            <div className="flex items-end gap-2">
              <Textarea
                className="max-h-28 min-h-10 resize-none rounded-sm leading-6"
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
              {isSubmitting ? (
                <Button type="button" size="icon" className="rounded-sm" onClick={handleStop} aria-label="응답 생성 중지" title="응답 생성 중지">
                  <span className="block size-3 rounded-[2px] bg-current" aria-hidden="true" />
                </Button>
              ) : (
                <Button type="submit" size="icon" className="rounded-sm" disabled={!user || !input.trim()} aria-label="메시지 보내기">
                  <Send />
                </Button>
              )}
            </div>
          </form>
        </section>
      ) : null}

      <Button
        type="button"
        size="icon"
        className="h-12 w-12 rounded-full shadow-[0_16px_36px_-20px_rgba(28,27,27,0.7)]"
        onClick={() => setIsOpen((current) => !current)}
        aria-label={isOpen ? "챗봇 닫기" : "챗봇 열기"}
      >
        {isOpen ? <X /> : <MessageCircle />}
      </Button>
    </div>
  );
}
