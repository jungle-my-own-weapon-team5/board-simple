"use client";

import { Bot, Check, ChevronLeft, ExternalLink, ImageIcon, Loader2, PanelRightClose, Plus, Save, Send, UserRound, Wand2, X } from "lucide-react";
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

const TAG_NAME_PATTERN = /^[0-9A-Za-z가-힣_]{1,50}$/;
const AGENT_CHAT_STORAGE_PREFIX = "history-board:editor-agent-chat:";
const MAX_STORED_AGENT_MESSAGES = 24;
const AGENT_PROGRESS_STEPS = [
  { label: "요청 의도 분석", percent: 25 },
  { label: "RAG 근거 검색", percent: 50 },
  { label: "외부 자료 확인", percent: 75 },
  { label: "답변 구성", percent: 90 },
];

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
  onRequestQuestion: (question: string) => void;
  isRequestingQuestion: boolean;
};

function AgentResultPanel({
  result,
  onApplyContent,
  onAppendContent,
  onApplyTitle,
  onAppendTags,
  onRequestQuestion,
  isRequestingQuestion
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
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-2 text-xs font-bold">
            <ExternalLink size={14} />
            외부 자료
          </p>
          {externalResources.map((resource) => (
            <a
              key={`${resource.provider}-${resource.url}`}
              href={resource.url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-border bg-background p-2 text-xs hover:bg-accent"
            >
              <span className="block break-words font-semibold">{resource.title}</span>
              <span className="mt-1 block break-words text-muted-foreground">
                {resource.provider} · {resource.description}
              </span>
            </a>
          ))}
        </div>
      ) : externalSearchLog ? (
        <div className="rounded-md border border-border bg-background p-2 text-xs text-muted-foreground">
          조선왕조실록에서 표시할 수 있는 외부 기사 링크를 찾지 못했습니다. 상태: {externalSearchLog.status}
        </div>
      ) : null}

      {result.suggested_content ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-bold">본문 초안</p>
          <div className="max-h-64 overflow-auto rounded-md border border-border bg-background p-3 text-sm leading-6 whitespace-pre-wrap break-words">
            {result.suggested_content}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={() => onApplyContent(result.suggested_content ?? "")}>
              본문에 적용
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => onAppendContent(result.suggested_content ?? "")}>
              아래에 추가
            </Button>
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
              className="rounded-md border border-border bg-background p-2 text-left text-xs leading-5 text-muted-foreground hover:bg-accent"
              disabled={isRequestingQuestion}
              onClick={() => onRequestQuestion(item)}
            >
              {item}
            </button>
          ))}
        </div>
      ) : null}

      {agentSteps.length ? (
        <details className="rounded-md border border-border bg-background p-2 text-xs">
          <summary className="cursor-pointer font-bold">Agent 실행 로그</summary>
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

function AgentProgressBubble({ stepIndex }: { stepIndex: number }) {
  const currentStep = AGENT_PROGRESS_STEPS[Math.min(stepIndex, AGENT_PROGRESS_STEPS.length - 1)];
  return (
    <div className="flex justify-start gap-2">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-card">
        <Bot size={15} />
      </div>
      <div className="w-[86%] rounded-lg border border-border bg-accent/50 px-3 py-3 text-sm shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Loader2 className="shrink-0 animate-spin" size={16} />
            <span className="truncate font-semibold">{currentStep.label}</span>
          </div>
          <span className="shrink-0 text-xs font-bold text-muted-foreground">{currentStep.percent}%</span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-background">
          <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${currentStep.percent}%` }} />
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          Agent가 단계별로 작업 중입니다. 완료되면 아래에 답변과 적용 버튼이 표시됩니다.
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
  const [agentProgressIndex, setAgentProgressIndex] = useState(0);
  const [isAgentCollapsed, setIsAgentCollapsed] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  useEffect(() => {
    if (!isAssisting) {
      setAgentProgressIndex(0);
      return;
    }
    const timer = window.setInterval(() => {
      setAgentProgressIndex((current) => Math.min(current + 1, AGENT_PROGRESS_STEPS.length - 1));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [isAssisting]);

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

  const handleAgentSend = async (nextMessage?: string) => {
    const message = (nextMessage ?? agentInput).trim();
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
    setAgentProgressIndex(0);
    setIsAssisting(true);

    try {
      const result = await aiApi.runEditorAgent({
        title,
        content,
        post_type: postType,
        category,
        message,
        history
      });
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

  const handleRequestQuestion = (question: string) => {
    setAgentInput(question);
    void handleAgentSend(question);
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
      className={`grid gap-5 ${
        isAgentCollapsed ? "lg:grid-cols-[minmax(0,1fr)_56px]" : "lg:grid-cols-[minmax(0,1fr)_380px]"
      }`}
      onSubmit={handleSubmit}
    >
      <div className="flex min-w-0 flex-col gap-5">
        <label className="flex flex-col gap-2 text-sm font-semibold">
          <span>Title</span>
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
            required
            placeholder="제목"
          />
        </label>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex flex-col gap-2 text-sm font-semibold">
            <span>글 유형</span>
            <select className="h-10 rounded-md border border-input bg-card px-3" value={postType} onChange={(event) => setPostType(event.target.value)}>
              {["질문", "토론", "발견", "사료 해석 요청", "가벼운 썰"].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-2 text-sm font-semibold">
            <span>카테고리</span>
            <select className="h-10 rounded-md border border-input bg-card px-3" value={category} onChange={(event) => setCategory(event.target.value)}>
              {["왕과 권력", "붕당과 정치", "전쟁과 외교", "인물 열전", "생활사와 문화", "사건 사고", "사료 발견", "오늘의 떡밥"].map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex flex-col gap-2">
          <label className="text-sm font-semibold" htmlFor="post-tags">태그</label>
          <div className="flex gap-2">
            <Input
              id="post-tags"
              value={tagInput}
              onChange={(event) => setTagInput(event.target.value)}
              onKeyDown={handleTagKeyDown}
              placeholder="태그 입력 후 Enter"
              maxLength={50}
            />
            <Button type="button" variant="outline" onClick={handleAddTag} disabled={!tagInput.trim() || selectedTags.length >= 10}>
              <Plus size={16} />
              추가
            </Button>
          </div>
          <div className="flex min-h-8 flex-wrap gap-2">
            {selectedTags.length === 0 ? <span className="text-sm text-muted-foreground">태그 없음</span> : null}
            {selectedTags.map((tag) => (
              <Badge variant="secondary" key={tag} className="gap-1 pr-1">
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
          </div>
        </div>
        <MarkdownEditor value={content} onChange={setContent} onUploadImage={handleUploadImage} />
        <section className="flex flex-col gap-3 border border-border bg-accent/40 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="flex items-center gap-2 text-base font-extrabold">
                <ImageIcon size={18} />
                AI 썸네일
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                제목과 본문을 바탕으로 조선 시각 taxonomy를 적용한 후보 3개를 만듭니다.
              </p>
            </div>
            <Button type="button" variant="outline" onClick={handleGenerateThumbnails} disabled={isGeneratingThumbnails}>
              {isGeneratingThumbnails ? <Loader2 className="animate-spin" /> : <Wand2 />}
              <span>{isGeneratingThumbnails ? "생성 중" : "AI 썸네일 만들기"}</span>
            </Button>
          </div>
          {thumbnailError ? <p className="text-sm font-semibold text-destructive">{thumbnailError}</p> : null}
          {selectedThumbnailUrl ? (
            <div className="flex items-center gap-3 rounded-md border border-border bg-background p-2 text-sm">
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
        <Button type="submit" className="w-fit" disabled={isSubmitting}>
          <Save />
          <span>{isSubmitting ? "Saving..." : submitLabel}</span>
        </Button>
      </div>

      <aside
        className={`flex min-h-[620px] min-w-0 flex-col border border-border bg-accent/40 lg:sticky lg:top-20 lg:h-[calc(100vh-6rem)] ${
          isAgentCollapsed ? "items-center gap-3 p-2" : "gap-3 p-4"
        }`}
      >
        {isAgentCollapsed ? (
          <>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => setIsAgentCollapsed(false)}
              aria-label="에디터 Agent 열기"
              title="에디터 Agent 열기"
            >
              <ChevronLeft />
            </Button>
            <button
              type="button"
              className="flex flex-1 items-center justify-center rounded-md border border-border bg-background px-2 py-3 text-xs font-bold text-muted-foreground [writing-mode:vertical-rl] hover:bg-accent"
              onClick={() => setIsAgentCollapsed(false)}
              aria-label="에디터 Agent 열기"
            >
              에디터 Agent
            </button>
          </>
        ) : (
          <>
        <div className="flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-base font-extrabold">
            <Wand2 size={18} />
            에디터 Agent
          </h2>
          <div className="flex items-center gap-1">
            <Button type="button" variant="ghost" size="icon" onClick={() => setIsAgentCollapsed(true)} aria-label="에디터 Agent 접기" title="에디터 Agent 접기">
              <PanelRightClose />
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={handleClearAgentChat} disabled={isAssisting}>
              <Plus size={14} />
              새 대화
            </Button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-background">
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
            {agentMessages.length === 0 ? (
              <div className="rounded-md border border-dashed border-border p-4 text-sm leading-6 text-muted-foreground">
                <p className="font-semibold text-foreground">무엇을 도와드릴까요?</p>
                <div className="mt-3 flex flex-col gap-2">
                  {["양녕대군은 어떤 사람이야?", "이 이야기로 게시글 본문 800자로 채워줘"].map((sample) => (
                    <button
                      key={sample}
                      type="button"
                      className="rounded-md border border-border bg-card px-3 py-2 text-left text-sm hover:bg-accent"
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
                  className={`max-w-[86%] rounded-lg px-3 py-2 text-sm leading-6 shadow-sm ${
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
                      onRequestQuestion={handleRequestQuestion}
                      isRequestingQuestion={isAssisting}
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

            {isAssisting ? <AgentProgressBubble stepIndex={agentProgressIndex} /> : null}
            <div ref={chatEndRef} />
          </div>

          <div className="border-t border-border p-3">
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
                aria-label="Agent 메시지 보내기"
              >
                {isAssisting ? <Loader2 className="animate-spin" /> : <Send />}
              </Button>
            </div>
          </div>
        </div>
          </>
        )}
      </aside>
    </form>
  );
}
