"use client";

import { ArrowLeft, Bot, Check, ExternalLink, FileInput, ImageIcon, Loader2, MessageSquarePlus, PanelRightClose, Plus, Save, Send, UserRound, Wand2, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import * as aiApi from "../api/ai";
import { ApiError, getAssetUrl } from "../api/client";
import * as postApi from "../api/posts";
import type { EditorAgentResponse, ThumbnailCandidate } from "../types";
import MarkdownEditor from "./MarkdownEditor";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";

type PostFormProps = {
  initialTitle?: string;
  initialContent?: string;
  initialPostType?: string;
  initialCategory?: string;
  initialTags?: string[];
  initialThumbnailUrl?: string | null;
  submitLabel: string;
  onSubmit: (payload: postApi.PostPayload) => Promise<void>;
};

type AgentChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: EditorAgentResponse;
};

type AgentProgress = Extract<aiApi.EditorAgentStreamEvent, { type: "progress" }>;

const TAG_NAME_PATTERN = /^[0-9A-Za-z가-힣_]{1,50}$/;
const AGENT_CHAT_STORAGE_PREFIX = "history-board:editor-agent-chat:";
const MAX_STORED_AGENT_MESSAGES = 24;
const INITIAL_AGENT_PROGRESS: AgentProgress = {
  type: "progress",
  step: "queued",
  label: "요청 준비",
  percent: 1,
};

function normalizeTagName(value: string) {
  const tag = value.trim().replace(/^#/, "").toLowerCase();
  return TAG_NAME_PATTERN.test(tag) ? tag : "";
}

function parseTagInput(value: string) {
  return value
    .split(/[,\s]+/)
    .map(normalizeTagName)
    .filter(Boolean);
}

function friendlyError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "로그인이 필요합니다. 다시 로그인해 주세요.";
    }
    if (error.status === 403) {
      return "이 글을 수정하거나 삭제할 권한이 없습니다.";
    }
  }
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

function makeMessageId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function normalizeStoredAgentMessages(value: unknown): AgentChatMessage[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is AgentChatMessage => {
      if (!item || typeof item !== "object") {
        return false;
      }
      const candidate = item as Partial<AgentChatMessage>;
      return (
        typeof candidate.id === "string" &&
        (candidate.role === "user" || candidate.role === "assistant") &&
        typeof candidate.content === "string"
      );
    })
    .slice(-MAX_STORED_AGENT_MESSAGES);
}

function actionLabel(action: string) {
  if (action === "fill_content") {
    return "본문 생성";
  }
  if (action === "revise_content") {
    return "본문 수정";
  }
  return "답변";
}

type AgentResultPanelProps = {
  result: EditorAgentResponse;
  onApplyContent: (content: string) => void;
  onAppendContent: (content: string) => void;
  onApplyTitle: (title: string) => void;
  onAppendTags: (tags: string[]) => void;
  onAppendQuestion: (question: string) => void;
};

function AgentResultPanel({
  result,
  onApplyContent,
  onAppendContent,
  onApplyTitle,
  onAppendTags,
  onAppendQuestion
}: AgentResultPanelProps) {
  const externalResources = result.external_resources ?? [];
  const externalSearchLog = (result.tool_logs ?? []).find(
    (log) => log.tool === "history.search_sillok" || log.tool === "mcp.external_history_search"
  );
  const tags = result.tags ?? [];
  const questions = result.questions ?? [];
  const agentSteps = result.agent_steps ?? [];

  return (
    <div className="mt-3 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{actionLabel(result.action)}</Badge>
        {result.weak_evidence ? <Badge variant="outline">근거 약함</Badge> : null}
      </div>

      {externalResources.length > 0 ? (
        <details className="rounded-sm border border-border bg-background p-2 text-xs">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-bold">
            <span className="flex items-center gap-2">
              <ExternalLink size={14} />
              외부 자료 {externalResources.length}건
            </span>
            <span className="text-muted-foreground">펼치기</span>
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {externalResources.slice(0, 6).map((resource) => (
              <div
                key={`${resource.provider}-${resource.url}`}
                className="rounded-sm border border-border/70 bg-card p-2"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <span className="block break-words font-semibold leading-5">{resource.title}</span>
                    <span className="mt-1 block truncate text-muted-foreground">{resource.provider}</span>
                  </div>
                  <Button type="button" variant="outline" size="sm" asChild className="h-8 shrink-0 rounded-sm px-2 text-xs">
                    <a href={resource.url} target="_blank" rel="noreferrer">
                      원문 보기
                    </a>
                  </Button>
                </div>
                {resource.description ? (
                  <p className="mt-2 line-clamp-2 break-words leading-5 text-muted-foreground">
                    {resource.description}
                  </p>
                ) : null}
              </div>
            ))}
            {externalResources.length > 6 ? (
              <p className="text-xs text-muted-foreground">나머지 {externalResources.length - 6}건은 AI 실행 로그에서 확인할 수 있습니다.</p>
            ) : null}
          </div>
        </details>
      ) : externalSearchLog ? (
        <div className="rounded-sm border border-border bg-background p-2 text-xs text-muted-foreground">
          조선왕조실록에서 표시할 수 있는 외부 기사 링크를 찾지 못했습니다. 상태: {externalSearchLog.status}
        </div>
      ) : null}

      {result.suggested_content ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" onClick={() => onApplyContent(result.suggested_content ?? "")}>
                <FileInput size={14} />
                에디터에 넣기
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={() => onAppendContent(result.suggested_content ?? "")}>
                아래에 추가
              </Button>
            </div>
            <p className="text-xs font-bold text-muted-foreground">본문 초안</p>
          </div>
          <div className="max-h-64 overflow-auto rounded-sm border border-border bg-background p-3 text-sm leading-6 whitespace-pre-wrap break-words">
            {result.suggested_content}
          </div>
        </div>
      ) : null}

      {result.suggested_title ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-bold">제안 제목</p>
          <Button
            type="button"
            variant="outline"
            className="h-auto justify-start whitespace-normal text-left"
            onClick={() => onApplyTitle(result.suggested_title ?? "")}
          >
            {result.suggested_title}
          </Button>
        </div>
      ) : null}

      {tags.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-bold">추천 태그</p>
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <Button key={tag} type="button" variant="secondary" size="sm" onClick={() => onAppendTags([tag])}>
                #{tag}
              </Button>
            ))}
          </div>
        </div>
      ) : null}

      {questions.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-bold">토론 질문</p>
          {questions.map((item) => (
            <button
              key={item}
              type="button"
              className="rounded-sm border border-border bg-background p-2 text-left text-xs leading-5 text-muted-foreground hover:bg-accent"
              onClick={() => onAppendQuestion(item)}
            >
              {item}
            </button>
          ))}
        </div>
      ) : null}

      {agentSteps.length ? (
        <details className="rounded-sm border border-border bg-background p-2 text-xs">
          <summary className="cursor-pointer font-bold">AI 실행 로그</summary>
          <div className="mt-2 flex flex-col gap-2">
            {agentSteps.map((step) => (
              <div key={`${step.name}-${step.output}`} className="rounded-sm bg-accent/40 p-2">
                <p className="font-semibold">{step.name}</p>
                <p className="mt-1 leading-5 text-muted-foreground">{step.output}</p>
              </div>
            ))}
            {result.evidence_summary ? <p className="leading-5 text-muted-foreground">{result.evidence_summary}</p> : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function AgentProgressBubble({ progress }: { progress: AgentProgress }) {
  return (
    <div className="flex justify-start gap-2">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-card">
        <Bot size={15} />
      </div>
      <div className="w-[86%] rounded-sm border border-border bg-accent/50 px-3 py-3 text-sm shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Loader2 className="shrink-0 animate-spin" size={16} />
            <span className="truncate font-semibold">{progress.label}</span>
          </div>
          <span className="shrink-0 text-xs font-bold text-muted-foreground">{progress.percent}%</span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-background">
          <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${progress.percent}%` }} />
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          백엔드 Agent가 실제 처리 단계별로 진행 상태를 보내고 있습니다.
        </p>
      </div>
    </div>
  );
}

export default function PostForm({
  initialTitle = "",
  initialContent = "",
  initialPostType = "토론",
  initialCategory = "왕과 권력",
  initialTags = [],
  initialThumbnailUrl = null,
  submitLabel,
  onSubmit
}: PostFormProps) {
  const [title, setTitle] = useState(initialTitle);
  const [content, setContent] = useState(initialContent);
  const [postType, setPostType] = useState(initialPostType);
  const [category, setCategory] = useState(initialCategory);
  const [selectedTags, setSelectedTags] = useState(() => Array.from(new Set(initialTags.map(normalizeTagName).filter(Boolean))));
  const [selectedThumbnailUrl, setSelectedThumbnailUrl] = useState<string | null>(initialThumbnailUrl);
  const [thumbnailCandidates, setThumbnailCandidates] = useState<ThumbnailCandidate[]>([]);
  const [thumbnailError, setThumbnailError] = useState<string | null>(null);
  const [isGeneratingThumbnails, setIsGeneratingThumbnails] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [agentInput, setAgentInput] = useState("");
  const [agentMessages, setAgentMessages] = useState<AgentChatMessage[]>([]);
  const [agentStorageKey, setAgentStorageKey] = useState<string | null>(null);
  const [agentProgress, setAgentProgress] = useState<AgentProgress>(INITIAL_AGENT_PROGRESS);
  const [isAgentCollapsed, setIsAgentCollapsed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAssisting, setIsAssisting] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const storageKey = `${AGENT_CHAT_STORAGE_PREFIX}${window.location.pathname}`;
    setAgentStorageKey(storageKey);
    const storedMessages = window.localStorage.getItem(storageKey);
    if (!storedMessages) {
      return;
    }
    try {
      const restoredMessages = normalizeStoredAgentMessages(JSON.parse(storedMessages));
      if (restoredMessages.length > 0) {
        setAgentMessages(restoredMessages);
      }
    } catch {
      window.localStorage.removeItem(storageKey);
    }
  }, []);

  useEffect(() => {
    if (!agentStorageKey) {
      return;
    }
    try {
      if (agentMessages.length === 0) {
        window.localStorage.removeItem(agentStorageKey);
        return;
      }
      window.localStorage.setItem(
        agentStorageKey,
        JSON.stringify(agentMessages.slice(-MAX_STORED_AGENT_MESSAGES))
      );
    } catch {
      // localStorage can be unavailable in hardened browser modes.
    }
  }, [agentMessages, agentStorageKey]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [agentMessages, isAssisting]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onSubmit({
        title,
        content,
        post_type: postType,
        category,
        tags: selectedTags,
        thumbnail_url: selectedThumbnailUrl
      });
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveDraft = () => {
    const savedAt = new Date();
    window.localStorage.setItem(
      `${AGENT_CHAT_STORAGE_PREFIX}draft:${window.location.pathname}`,
      JSON.stringify({
        title,
        content,
        post_type: postType,
        category,
        tags: selectedTags,
        thumbnail_url: selectedThumbnailUrl,
        saved_at: savedAt.toISOString()
      })
    );
    setDraftSavedAt(savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  };

  const handleAgentSend = async () => {
    const message = agentInput.trim();
    if (!message || isAssisting) {
      return;
    }

    const history = agentMessages.slice(-8).map((item) => ({
      role: item.role,
      content: item.content
    }));
    const userMessage: AgentChatMessage = {
      id: makeMessageId(),
      role: "user",
      content: message
    };

    setError(null);
    setAgentInput("");
    setAgentMessages((current) => [...current, userMessage]);
    setAgentProgress(INITIAL_AGENT_PROGRESS);
    setIsAssisting(true);

    try {
      const payload: aiApi.EditorAgentPayload = {
        title,
        content,
        post_type: postType,
        category,
        message,
        history
      };
      let result: EditorAgentResponse | null = null;
      try {
        await aiApi.streamEditorAgent(payload, (event) => {
          if (event.type === "progress") {
            setAgentProgress(event);
            return;
          }
          result = event.response;
        });
      } catch {
        result = await aiApi.runEditorAgent(payload);
      }
      if (!result) {
        throw new ApiError(0, "AI 응답을 받지 못했습니다.");
      }
      const assistantMessage: AgentChatMessage = {
        id: makeMessageId(),
        role: "assistant",
        content: result.agent_message,
        result
      };
      setAgentMessages((current) => [...current, assistantMessage]);
      if (result.category) {
        setCategory(result.category);
      }
    } catch (err) {
      setAgentMessages((current) => [
        ...current,
        {
          id: makeMessageId(),
          role: "assistant",
          content: friendlyError(err)
        }
      ]);
    } finally {
      setIsAssisting(false);
    }
  };

  const handleAgentKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleAgentSend();
    }
  };

  const handleClearAgentChat = () => {
    setAgentInput("");
    setAgentMessages([]);
    if (agentStorageKey) {
      try {
        window.localStorage.removeItem(agentStorageKey);
      } catch {
        // localStorage can be unavailable in hardened browser modes.
      }
    }
  };

  const handleUploadImage = async (file: File) => {
    try {
      const result = await postApi.uploadPostImage(file);
      return getAssetUrl(result.image_url);
    } catch (err) {
      throw new Error(friendlyError(err));
    }
  };

  const handleGenerateThumbnails = async () => {
    setError(null);
    setThumbnailError(null);
    setIsGeneratingThumbnails(true);
    try {
      const result = await postApi.generateDraftThumbnailCandidates({
        title,
        content,
        category,
        tags: selectedTags
      });
      setThumbnailCandidates(result.candidates);
      const firstImage = result.candidates.find((candidate) => candidate.image_url)?.image_url ?? null;
      setSelectedThumbnailUrl(firstImage);
      if (!firstImage) {
        setThumbnailError("이미지 생성 API 키가 없거나 생성에 실패했습니다. 후보 프롬프트만 확인할 수 있습니다.");
      }
    } catch (err) {
      setThumbnailCandidates([]);
      setSelectedThumbnailUrl(null);
      setThumbnailError(friendlyError(err));
    } finally {
      setIsGeneratingThumbnails(false);
    }
  };

  const appendTags = (nextTags: string[]) => {
    setSelectedTags((current) => {
      const next = [...current];
      for (const rawTag of nextTags) {
        const tag = normalizeTagName(rawTag);
        if (tag && !next.includes(tag)) {
          next.push(tag);
        }
      }
      return next.slice(0, 10);
    });
  };

  const handleAddTag = () => {
    const nextTags = parseTagInput(tagInput);
    if (nextTags.length === 0) {
      return;
    }
    appendTags(nextTags);
    setTagInput("");
  };

  const handleTagKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === "," || event.key === " ") {
      event.preventDefault();
      handleAddTag();
    }
  };

  const removeTag = (tag: string) => {
    setSelectedTags((current) => current.filter((item) => item !== tag));
  };

  return (
    <form
      className={`grid gap-6 ${
        isAgentCollapsed ? "lg:grid-cols-[minmax(0,1fr)_56px]" : "lg:grid-cols-[minmax(0,1fr)_360px]"
      }`}
      onSubmit={handleSubmit}
    >
      <div className="flex min-w-0 flex-col gap-6">
        <label className="block">
          <span className="sr-only">제목</span>
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
            required
            placeholder="역사적 통찰의 제목을 입력하세요"
            className="h-auto rounded-none border-0 border-b border-border/60 bg-transparent px-0 py-4 font-serif-display text-3xl font-bold leading-[1.25] shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 sm:text-4xl"
          />
        </label>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-2 text-sm font-semibold">
            <span className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">게시글 유형</span>
            <select className="h-11 rounded-sm border border-input bg-accent/55 px-3 text-sm font-semibold outline-none focus:border-secondary focus:ring-1 focus:ring-secondary/40" value={postType} onChange={(event) => setPostType(event.target.value)}>
              {["질문", "토론", "발견", "사료 해석 요청", "가벼운 썰"].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-2 text-sm font-semibold">
            <span className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">카테고리</span>
            <select className="h-11 rounded-sm border border-input bg-accent/55 px-3 text-sm font-semibold outline-none focus:border-secondary focus:ring-1 focus:ring-secondary/40" value={category} onChange={(event) => setCategory(event.target.value)}>
              {["왕과 권력", "붕당과 정치", "전쟁과 외교", "인물 열전", "생활사와 문화", "사건 사고", "사료 발견", "오늘의 떡밥"].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex flex-col gap-2">
          <label className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground" htmlFor="post-tags">태그</label>
          <div className="flex min-h-12 flex-wrap items-center gap-2 border border-border bg-accent/45 p-2">
            {selectedTags.map((tag) => (
              <Badge variant="secondary" key={tag} className="gap-1 border-secondary/20 bg-secondary/10 pr-1 text-secondary">
                #{tag}
                <button
                  type="button"
                  className="rounded-sm p-0.5 hover:bg-background"
                  onClick={() => removeTag(tag)}
                  aria-label={`${tag} 태그 제거`}
                >
                  <X size={12} />
                </button>
              </Badge>
            ))}
            <Input
              id="post-tags"
              value={tagInput}
              onChange={(event) => setTagInput(event.target.value)}
              onKeyDown={handleTagKeyDown}
              placeholder="태그 입력 후 Enter"
              maxLength={50}
              className="h-8 min-w-40 flex-1 border-0 bg-transparent px-1 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
            />
            <Button type="button" variant="outline" onClick={handleAddTag} disabled={!tagInput.trim() || selectedTags.length >= 10}>
              <Plus size={16} />
              추가
            </Button>
          </div>
          {selectedTags.length === 0 ? <span className="text-xs text-muted-foreground">태그는 본문 주제와 사료 키워드 중심으로 추가하세요.</span> : null}
        </div>
        <MarkdownEditor value={content} onChange={setContent} onUploadImage={handleUploadImage} />
        <section className="bal-card relative flex flex-col gap-3 overflow-hidden border border-border bg-accent/40 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="font-serif-display flex items-center gap-2 text-lg font-bold">
                <ImageIcon size={18} />
                AI 썸네일
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                제목과 본문을 바탕으로 조선 시각 taxonomy를 적용한 후보 3개를 만듭니다.
              </p>
            </div>
            <Button type="button" variant="outline" className="rounded-sm" onClick={handleGenerateThumbnails} disabled={isGeneratingThumbnails}>
              {isGeneratingThumbnails ? <Loader2 className="animate-spin" /> : <Wand2 />}
              <span>{isGeneratingThumbnails ? "생성 중" : "AI 썸네일 만들기"}</span>
            </Button>
          </div>
          {thumbnailError ? <p className="text-sm font-semibold text-destructive">{thumbnailError}</p> : null}
          {selectedThumbnailUrl ? (
            <div className="flex items-center gap-3 rounded-sm border border-border bg-background p-2 text-sm">
              <img
                src={getAssetUrl(selectedThumbnailUrl)}
                alt="선택된 AI 썸네일"
                className="h-16 w-24 shrink-0 object-cover"
              />
              <div className="min-w-0">
                <p className="font-bold">선택된 썸네일</p>
                <p className="truncate text-muted-foreground">{selectedThumbnailUrl}</p>
              </div>
            </div>
          ) : null}
          {thumbnailCandidates.length > 0 ? (
            <div className="grid gap-3 md:grid-cols-3">
              {thumbnailCandidates.map((candidate, index) => {
                const isSelected = Boolean(candidate.image_url && candidate.image_url === selectedThumbnailUrl);
                return (
                  <button
                    key={`${candidate.image_url ?? "candidate"}-${index}`}
                    type="button"
                    className={`flex min-w-0 flex-col gap-2 border bg-background p-2 text-left ${
                      isSelected ? "border-primary ring-2 ring-primary/30" : "border-border"
                    } ${candidate.image_url ? "hover:bg-accent" : "cursor-not-allowed opacity-70"}`}
                    disabled={!candidate.image_url}
                    onClick={() => setSelectedThumbnailUrl(candidate.image_url)}
                  >
                    {candidate.image_url ? (
                      <img
                        src={getAssetUrl(candidate.image_url)}
                        alt={`AI 썸네일 후보 ${index + 1}`}
                        className="aspect-[3/2] w-full object-cover"
                      />
                    ) : (
                      <div className="flex aspect-[3/2] w-full items-center justify-center bg-accent text-xs text-muted-foreground">
                        이미지 없음
                      </div>
                    )}
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-bold">후보 {index + 1}</span>
                      {isSelected ? <Check size={16} /> : null}
                    </div>
                    <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">
                      {candidate.visual_brief}
                    </p>
                  </button>
                );
              })}
            </div>
          ) : null}
        </section>
        {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      </div>

      <aside
        className={`min-w-0 lg:sticky lg:top-20 lg:h-[calc(100vh-13rem)] ${
          isAgentCollapsed
            ? "flex min-h-0 items-start justify-center border-0 bg-transparent px-0 py-2"
            : "bal-card relative flex min-h-[620px] flex-col overflow-hidden border border-border bg-accent/45 shadow-sm lg:min-h-0"
        }`}
      >
        {isAgentCollapsed ? (
          <div className="sticky top-24">
            <button
              type="button"
              onClick={() => setIsAgentCollapsed(false)}
              className="flex h-12 w-12 items-center justify-center rounded-sm border border-border bg-card text-foreground shadow-sm transition hover:bg-accent"
              aria-label="AI 도우미 열기"
              title="AI 도우미 열기"
            >
              <Wand2 size={18} />
              <span className="sr-only">AI 도우미 열기</span>
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-3 border-b border-border bg-accent/70 p-4">
              <h2 className="flex min-w-0 items-center gap-2 text-sm font-bold uppercase tracking-[0.08em] text-primary">
                <Wand2 size={18} className="shrink-0 text-secondary" />
                <span className="truncate">Archivist AI</span>
              </h2>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={handleClearAgentChat}
                  disabled={isAssisting}
                  aria-label="새 대화"
                  title="새 대화"
                >
                  <MessageSquarePlus />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setIsAgentCollapsed(true)}
                  aria-label="AI 도우미 접기"
                  title="AI 도우미 접기"
                >
                  <PanelRightClose />
                </Button>
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
                {agentMessages.length === 0 ? (
                  <div className="rounded-sm border border-dashed border-border p-4 text-sm leading-6 text-muted-foreground">
                    <p className="font-semibold text-foreground">무엇을 도와드릴까요?</p>
                    <div className="mt-3 flex flex-col gap-2">
                      {["양녕대군은 어떤 사람이야?", "이 이야기로 게시글 본문 800자로 채워줘"].map((sample) => (
                        <button
                          key={sample}
                          type="button"
                          className="rounded-sm border border-border bg-card px-3 py-2 text-left text-sm hover:bg-accent"
                          onClick={() => setAgentInput(sample)}
                        >
                          {sample}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                {agentMessages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex gap-2 ${message.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    {message.role === "assistant" ? (
                      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-card">
                        <Bot size={15} />
                      </div>
                    ) : null}
                    <div
                      className={`max-w-[86%] rounded-sm px-3 py-2 text-sm leading-6 shadow-sm ${
                        message.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "border border-border bg-accent/50 text-foreground"
                      }`}
                    >
                      <div className="whitespace-pre-wrap break-words">{message.content}</div>
                      {message.result ? (
                        <AgentResultPanel
                          result={message.result}
                          onApplyContent={setContent}
                          onAppendContent={(nextContent) => setContent((current) => `${current.trim()}\n\n${nextContent}`.trim())}
                          onApplyTitle={setTitle}
                          onAppendTags={appendTags}
                          onAppendQuestion={(question) => setContent((current) => `${current.trim()}\n\n${question}`.trim())}
                        />
                      ) : null}
                    </div>
                    {message.role === "user" ? (
                      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-card">
                        <UserRound size={15} />
                      </div>
                    ) : null}
                  </div>
                ))}

                {isAssisting ? <AgentProgressBubble progress={agentProgress} /> : null}
                <div ref={chatEndRef} />
              </div>

              <div className="border-t border-border bg-accent/70 p-3">
                <div className="flex items-end gap-2">
                  <Textarea
                    value={agentInput}
                    onChange={(event) => setAgentInput(event.target.value)}
                    onKeyDown={handleAgentKeyDown}
                    rows={3}
                    className="max-h-40 resize-none"
                    placeholder="메시지를 입력하세요"
                  />
                  <Button
                    type="button"
                    size="icon"
                    onClick={() => void handleAgentSend()}
                    disabled={isAssisting || !agentInput.trim()}
                    aria-label="AI 도우미 메시지 보내기"
                  >
                    {isAssisting ? <Loader2 className="animate-spin" /> : <Send />}
                  </Button>
                </div>
              </div>
            </div>
          </>
        )}
      </aside>

      <footer className="col-span-full -mx-4 border-t border-border bg-background/95 px-4 py-4 shadow-[0_-12px_28px_-26px_rgba(28,27,27,0.6)] sm:-mx-6 sm:px-6 lg:col-span-1 lg:col-start-1 lg:mx-0 lg:px-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-4">
            <Button type="button" variant="ghost" asChild className="rounded-sm">
              <Link href="/">
                <ArrowLeft />
                <span>게시판으로 돌아가기</span>
              </Link>
            </Button>
            <span className="text-xs font-semibold text-muted-foreground">
              {draftSavedAt ? `초안이 저장되었습니다 (${draftSavedAt})` : "초안은 이 브라우저에 임시 저장할 수 있습니다"}
            </span>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button type="button" variant="outline" disabled={isSubmitting} onClick={handleSaveDraft}>
              임시 저장
            </Button>
            <Button type="submit" className="bg-secondary text-secondary-foreground hover:bg-secondary/90" disabled={isSubmitting}>
              <Save />
              <span>{isSubmitting ? "저장 중..." : submitLabel}</span>
            </Button>
          </div>
        </div>
      </footer>
    </form>
  );
}
