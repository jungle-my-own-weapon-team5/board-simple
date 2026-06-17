"use client";

import {
  Gavel,
  Loader2,
  ListChecks,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Search,
  SlidersHorizontal
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ComponentProps, ReactNode, SubmitEvent } from "react";

import * as aiApi from "../api/ai";
import * as ragApi from "../api/rag";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import type {
  AnswerDraftResponse,
  DisputeIssuesResponse,
  LegalDocumentType,
  RagSearchItem,
  RagSearchMode,
  RagSearchResponse
} from "../types";

const DOCUMENT_TYPE_OPTIONS: Array<{
  value: LegalDocumentType | "";
  label: string;
  disabled?: boolean;
}> = [
  { value: "", label: "전체" },
  { value: "statute", label: "법령" },
  { value: "case", label: "판례 - 후속 지원", disabled: true },
  { value: "interpretation", label: "해석례 - 후속 지원", disabled: true },
  { value: "admin_appeal", label: "행정심판 - 후속 지원", disabled: true },
  { value: "user_file", label: "사용자 문서 - 후속 지원", disabled: true },
  { value: "memo", label: "메모 - 후속 지원", disabled: true }
];

type GeneratedBlockTitle = "쟁점 정리" | "답변 초안";

const GENERATED_EMPTY_TEXT: Record<GeneratedBlockTitle, string> = {
  "쟁점 정리": "쟁점 정리를 실행하면 결과가 표시됩니다.",
  "답변 초안": "답변 초안을 실행하면 결과가 표시됩니다."
};

const DEFAULT_FACTS =
  "임대차 계약이 종료되었지만 임대인이 보증금을 반환하지 않고 있습니다.";
const DEFAULT_QUESTION = "검토해야 할 쟁점과 답변 초안 방향을 알려주세요.";
const RESULT_PANEL_CARD_CLASS = "flex h-[34rem] flex-col xl:h-[calc(100vh-6rem)]";
const RESULT_PANEL_CONTENT_CLASS = "min-h-0 flex-1 overflow-y-auto";
const EMPTY_RESULT_PANEL_CARD_CLASS = "flex min-h-40 flex-col";

type ActionState =
  | "idle"
  | "searching"
  | "issues"
  | "draft"
  | "analysis";

export default function DisputeAssistantPage() {
  // 입력값과 실행 결과를 분리해 검색 결과를 보존한 상태에서 초안만 다시 생성할 수 있게 합니다.
  const [facts, setFacts] = useState(DEFAULT_FACTS);
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [searchMode, setSearchMode] = useState<RagSearchMode>("issue_spotting");
  const [documentType, setDocumentType] = useState<LegalDocumentType | "">("");
  const [topK, setTopK] = useState("");
  const [maxChunksPerDocument, setMaxChunksPerDocument] = useState("");
  const [scoreThreshold, setScoreThreshold] = useState("");
  const [searchResult, setSearchResult] = useState<RagSearchResponse | null>(null);
  const [issuesResult, setIssuesResult] = useState<DisputeIssuesResponse | null>(null);
  const [draftResult, setDraftResult] = useState<AnswerDraftResponse | null>(null);
  const [activeAction, setActiveAction] = useState<ActionState>("idle");
  const [showWorkingStatus, setShowWorkingStatus] = useState(false);
  const [isSearchPanelOpen, setIsSearchPanelOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const trimmedFacts = facts.trim();
  const trimmedQuestion = question.trim();
  const isBusy = activeAction !== "idle";
  const isFullAnalysisRunning = activeAction === "analysis";
  const isSearchRunning = activeAction === "searching";
  const isIssuesRunning = activeAction === "issues";
  const isDraftRunning = activeAction === "draft";
  const workingMessage = workingMessageForAction(activeAction);
  const isRunnable = trimmedFacts.length > 0 && trimmedQuestion.length > 0 && !isBusy;
  const retrievalOptions = useMemo(
    () => ({
      search_mode: searchMode,
      top_k: optionalBoundedInteger(topK, 1, 100),
      score_threshold: optionalBoundedNumber(scoreThreshold, 0, 1),
      max_chunks_per_document: optionalBoundedInteger(maxChunksPerDocument, 1, 100)
    }),
    [maxChunksPerDocument, scoreThreshold, searchMode, topK]
  );

  useEffect(() => {
    if (activeAction === "idle") {
      setShowWorkingStatus(false);
      return;
    }

    const timerId = window.setTimeout(() => {
      setShowWorkingStatus(true);
    }, 1000);

    return () => window.clearTimeout(timerId);
  }, [activeAction]);

  const buildSearchPayload = () => ({
    query: `${trimmedFacts}\n${trimmedQuestion}`,
    ...retrievalOptions,
    filters: documentType ? { document_types: [documentType] } : undefined
  });

  const buildAgentPayload = () => ({
    facts: trimmedFacts,
    question: trimmedQuestion,
    ...retrievalOptions
  });

  const handleFullAnalysis = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isRunnable) {
      return;
    }

    setError(null);
    setSearchResult(null);
    setIssuesResult(null);
    setDraftResult(null);
    try {
      setActiveAction("analysis");
      const result = await aiApi.createFullAnalysis({
        ...buildAgentPayload(),
        tone: "formal"
      });
      setSearchResult(result.search);
      setIssuesResult(result.issues);
      setDraftResult(result.draft);
    } catch (err) {
      setError(messageFromError(err, "전체 분석에 실패했습니다."));
    } finally {
      setActiveAction("idle");
    }
  };

  // 자료 검색은 답변 생성을 하지 않고 backend retrieval 결과만 받아옵니다.
  const handleSearch = async () => {
    if (!isRunnable) {
      return;
    }

    setError(null);
    setActiveAction("searching");
    try {
      const result = await ragApi.searchRagDocuments(buildSearchPayload());
      setSearchResult(result);
    } catch (err) {
      setError(messageFromError(err, "자료 검색에 실패했습니다."));
    } finally {
      setActiveAction("idle");
    }
  };

  // 쟁점 정리는 같은 입력과 검색 옵션을 Orchestrator Agent에 전달합니다.
  const handleIssues = async () => {
    if (!isRunnable) {
      return;
    }

    setError(null);
    setActiveAction("issues");
    try {
      const result = await aiApi.createDisputeIssues(buildAgentPayload());
      setIssuesResult(result);
    } catch (err) {
      setError(messageFromError(err, "쟁점 정리에 실패했습니다."));
    } finally {
      setActiveAction("idle");
    }
  };

  // 답변 초안은 citation 검증이 끝난 backend 응답만 표시합니다.
  const handleDraft = async () => {
    if (!isRunnable) {
      return;
    }

    setError(null);
    setActiveAction("draft");
    try {
      const result = await aiApi.createAnswerDraft({
        ...buildAgentPayload(),
        tone: "formal",
      });
      setDraftResult(result);
    } catch (err) {
      setError(messageFromError(err, "답변 초안 생성에 실패했습니다."));
    } finally {
      setActiveAction("idle");
    }
  };

  return (
    <section className="relative left-1/2 flex w-[min(calc(100vw-2rem),88rem)] -translate-x-1/2 flex-col gap-5">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Gavel className="size-7 text-primary" />
          <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">
            AI 법률 검토
          </h1>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          사실관계와 질문을 기준으로 내부 RAG 검색, 쟁점 정리, 답변 초안을 실행합니다.
        </p>
      </div>

      <form className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]" onSubmit={handleFullAnalysis}>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">입력</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <label className="grid gap-2 text-sm font-semibold">
              사실관계
              <Textarea
                value={facts}
                onChange={(event) => setFacts(event.target.value)}
                className="min-h-72 resize-y lg:min-h-[22rem]"
                maxLength={20000}
              />
            </label>
            <label className="grid gap-2 text-sm font-semibold">
              질문
              <Textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                className="min-h-24 resize-y"
                maxLength={5000}
              />
            </label>
            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              <ActionButton
                icon={<Gavel />}
                isLoading={isFullAnalysisRunning}
                disabled={!isRunnable}
                type="submit"
                size="lg"
                className="w-full sm:w-auto"
              >
                전체 분석
              </ActionButton>
              <div className="flex flex-wrap gap-2">
                <ActionButton
                  icon={<Search />}
                  isLoading={isSearchRunning && !isFullAnalysisRunning}
                  disabled={!isRunnable}
                  type="button"
                  onClick={handleSearch}
                  variant="outline"
                >
                  근거만 검색
                </ActionButton>
                <ActionButton
                  icon={<ListChecks />}
                  isLoading={isIssuesRunning && !isFullAnalysisRunning}
                  disabled={!isRunnable}
                  type="button"
                  onClick={handleIssues}
                  variant="outline"
                >
                  쟁점 다시 생성
                </ActionButton>
                <ActionButton
                  icon={<RefreshCw />}
                  isLoading={isDraftRunning && !isFullAnalysisRunning}
                  disabled={!isRunnable}
                  type="button"
                  onClick={handleDraft}
                  variant="secondary"
                >
                  초안 다시 생성
                </ActionButton>
              </div>
            </div>
            {showWorkingStatus && workingMessage ? (
              <div
                className="flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm text-muted-foreground"
                role="status"
                aria-live="polite"
              >
                <Loader2 className="size-4 animate-spin text-primary" />
                <span>{workingMessage}</span>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-lg">
              <SlidersHorizontal className="size-5 text-primary" />
              검색 설정
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant={searchMode === "focused_answer" ? "default" : "outline"}
                onClick={() => setSearchMode("focused_answer")}
              >
                집중 답변
              </Button>
              <Button
                type="button"
                variant={searchMode === "issue_spotting" ? "default" : "outline"}
                onClick={() => setSearchMode("issue_spotting")}
              >
                쟁점 탐지
              </Button>
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              집중 답변은 좁은 근거를, 쟁점 탐지는 쟁점별 후보를 넓게 검색합니다.
            </p>
            <label className="grid gap-2 text-sm font-semibold">
              문서 유형
              <select
                value={documentType}
                onChange={(event) => setDocumentType(event.target.value as LegalDocumentType | "")}
                className="h-10 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {DOCUMENT_TYPE_OPTIONS.map((option) => (
                  <option value={option.value} key={option.value} disabled={option.disabled}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-xs leading-5 text-muted-foreground">
              현재 자동 수집·색인은 법령만 지원합니다. 법령에는 법률, 대통령령, 총리령, 부령 계열이 포함됩니다.
            </p>
            <NumberField
              label="Top K"
              value={topK}
              onChange={(value) => setTopK(normalizeIntegerInput(value, 1, 100))}
              min={1}
              max={100}
              step={1}
              placeholder="모드 기본값"
              description="쟁점별로 검색할 후보 청크 수입니다. 비워두면 검색 모드의 기본값을 사용합니다."
            />
            <NumberField
              label="문서당 청크"
              value={maxChunksPerDocument}
              onChange={(value) => setMaxChunksPerDocument(normalizeIntegerInput(value, 1, 100))}
              min={1}
              max={100}
              step={1}
              placeholder="제한 없음"
              description="한 문서가 결과를 과도하게 차지하지 않도록 문서별 청크 수를 제한합니다. 비워두면 제한하지 않습니다."
            />
            <label className="grid gap-2 text-sm font-semibold">
              Score Threshold
              <Input
                type="number"
                value={scoreThreshold}
                onChange={(event) => setScoreThreshold(normalizeDecimalInput(event.target.value, 0, 1))}
                inputMode="decimal"
                min={0}
                max={1}
                step={0.01}
                placeholder="선택"
              />
              <span className="text-xs font-normal leading-5 text-muted-foreground">
                지정한 점수 미만의 검색 결과를 제외합니다. 비워두면 점수로 강제 제외하지 않고 후속 검토 단계에 맡깁니다.
              </span>
            </label>
          </CardContent>
        </Card>
      </form>

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">
          {error}
        </div>
      ) : null}

      <div
        className={
          isSearchPanelOpen
            ? "grid gap-4 xl:grid-cols-[18rem_minmax(0,1fr)] 2xl:grid-cols-[20rem_minmax(0,1fr)]"
            : "grid gap-4 xl:grid-cols-[3.5rem_minmax(0,1fr)]"
        }
      >
        <SearchResultsPanel
          result={searchResult}
          isOpen={isSearchPanelOpen}
          onToggle={() => setIsSearchPanelOpen((value) => !value)}
        />
        <GeneratedResultPanel issues={issuesResult} draft={draftResult} />
      </div>
    </section>
  );
}

type ActionButtonProps = ComponentProps<typeof Button> & {
  icon: ReactNode;
  isLoading: boolean;
};

function ActionButton({ children, icon, isLoading, ...props }: ActionButtonProps) {
  return (
    <Button {...props}>
      {isLoading ? <Loader2 className="animate-spin" /> : icon}
      <span>{children}</span>
    </Button>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  placeholder,
  description
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min: number;
  max: number;
  step?: number;
  placeholder?: string;
  description?: string;
}) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      {label}
      <Input
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
      />
      {description ? (
        <span className="text-xs font-normal leading-5 text-muted-foreground">
          {description}
        </span>
      ) : null}
    </label>
  );
}

function SearchResultsPanel({
  result,
  isOpen,
  onToggle
}: {
  result: RagSearchResponse | null;
  isOpen: boolean;
  onToggle: () => void;
}) {
  if (!isOpen) {
    return (
      <Card className="xl:sticky xl:top-20">
        <CardContent className="flex flex-col items-center gap-3 p-3">
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={onToggle}
            aria-label="검색 결과 펼치기"
            title="검색 결과 펼치기"
          >
            <PanelLeftOpen />
          </Button>
          {result ? (
            <Badge variant="secondary" className="px-2 py-1">
              {result.items.length}
            </Badge>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      className={`${result ? RESULT_PANEL_CARD_CLASS : EMPTY_RESULT_PANEL_CARD_CLASS} xl:sticky xl:top-20`}
    >
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="text-lg">검색 결과</CardTitle>
            {result ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Run #{result.run_id} · {result.items.length}건
              </p>
            ) : null}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onToggle}
            aria-label="검색 결과 접기"
            title="검색 결과 접기"
          >
            <PanelLeftClose />
          </Button>
        </div>
      </CardHeader>
      <CardContent className={`grid gap-2 ${RESULT_PANEL_CONTENT_CLASS}`}>
        {!result ? (
          <EmptyState text="검색을 실행하면 관련 청크가 표시됩니다." />
        ) : result.items.length === 0 ? (
          <EmptyState text="검색 결과가 없습니다." />
        ) : (
          result.items.map((item) => <SearchResultItemView item={item} key={item.chunk_id} />)
        )}
      </CardContent>
    </Card>
  );
}

// 검색 결과는 답변과 분리해 표시하고, 각 청크의 원문·점수·출처를 바로 확인할 수 있게 합니다.
function SearchResultItemView({ item }: { item: RagSearchItem }) {
  return (
    <article className="rounded-md border border-border bg-background p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-extrabold leading-5 [overflow-wrap:anywhere]">
            {item.title}
          </h3>
          <p className="text-xs text-muted-foreground">
            {item.heading || "제목 없음"} · 점수 {item.score.toFixed(3)}
          </p>
        </div>
        <Badge variant="outline">#{item.rank}</Badge>
      </div>
      <p className="mt-2 max-h-36 overflow-y-auto whitespace-pre-wrap text-xs leading-5 [overflow-wrap:anywhere]">
        {item.content}
      </p>
      {item.source_url ? (
        <a
          href={item.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-xs font-semibold text-primary hover:underline"
        >
          출처 열기
        </a>
      ) : null}
    </article>
  );
}

// 생성 결과는 쟁점 정리와 답변 초안을 나누어 보여주되, citation 표시는 같은 규칙을 재사용합니다.
function GeneratedResultPanel({
  issues,
  draft
}: {
  issues: DisputeIssuesResponse | null;
  draft: AnswerDraftResponse | null;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <GeneratedBlock
        title="쟁점 정리"
        runId={issues?.run_id}
        body={issues?.issues_text}
        citations={issues?.citations ?? []}
        disclaimer={issues?.disclaimer}
      />
      <GeneratedBlock
        title="답변 초안"
        runId={draft?.run_id}
        body={draft?.draft}
        citations={draft?.citations ?? []}
        disclaimer={draft?.disclaimer}
      />
    </div>
  );
}

function GeneratedBlock({
  title,
  runId,
  body,
  citations,
  disclaimer
}: {
  title: GeneratedBlockTitle;
  runId?: number;
  body?: string | null;
  citations: Array<{
    chunk_id: number | null;
    title: string | null;
    source_url: string | null;
    heading: string | null;
    rank: number | null;
  }>;
  disclaimer?: string | null;
}) {
  return (
    <Card className={body ? RESULT_PANEL_CARD_CLASS : EMPTY_RESULT_PANEL_CARD_CLASS}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-lg">{title}</CardTitle>
          {runId ? <Badge variant="secondary">Run #{runId}</Badge> : null}
        </div>
      </CardHeader>
      <CardContent className={`grid gap-3 ${RESULT_PANEL_CONTENT_CLASS}`}>
        {body ? (
          <p className="whitespace-pre-wrap text-sm leading-7 [overflow-wrap:anywhere]">
            {body}
          </p>
        ) : (
          <EmptyState text={GENERATED_EMPTY_TEXT[title]} />
        )}
        {citations.length > 0 ? (
          <div className="grid gap-2">
            <h4 className="text-sm font-extrabold">인용 출처</h4>
            <div className="flex flex-wrap gap-2">
              {citations.map((citation, index) => (
                <CitationBadge citation={citation} key={`${citation.chunk_id}-${index}`} />
              ))}
            </div>
          </div>
        ) : null}
        {disclaimer ? (
          <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
            {disclaimer}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CitationBadge({
  citation
}: {
  citation: {
    chunk_id: number | null;
    title: string | null;
    source_url: string | null;
    heading: string | null;
    rank: number | null;
  };
}) {
  const label = `${citation.rank ? `#${citation.rank} ` : ""}${citation.title || "출처"}`;
  if (citation.source_url) {
    return (
      <a href={citation.source_url} target="_blank" rel="noreferrer">
        <Badge variant="outline" className="max-w-full gap-1 py-1">
          <span className="truncate">{label}</span>
        </Badge>
      </a>
    );
  }
  return (
    <Badge variant="outline" className="max-w-full py-1">
      <span className="truncate">{label}</span>
    </Badge>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

function workingMessageForAction(action: ActionState): string | null {
  if (action === "analysis") {
    return "공식 법령 색인, 근거 검토, 쟁점 정리, 답변 초안을 한 번에 진행하는 중입니다.";
  }
  if (action === "searching") {
    return "근거 자료를 검색하고 필요한 경우 공식 법령을 색인하는 중입니다.";
  }
  if (action === "issues") {
    return "쟁점을 정리하고 검색된 근거와 대조하는 중입니다.";
  }
  if (action === "draft") {
    return "답변 초안을 작성하고 citation을 검증하는 중입니다.";
  }
  return null;
}

function normalizeIntegerInput(value: string, min: number, max: number) {
  const digits = value.replace(/\D/g, "");
  if (!digits) {
    return "";
  }
  const parsed = Number(digits);
  if (!Number.isFinite(parsed)) {
    return "";
  }
  return String(Math.min(Math.max(parsed, min), max));
}

function normalizeDecimalInput(value: string, min: number, max: number) {
  const normalized = value
    .replace(/,/g, ".")
    .replace(/[^\d.]/g, "")
    .replace(/(\..*)\./g, "$1");

  if (!normalized) {
    return "";
  }
  if (normalized === ".") {
    return "0.";
  }

  const parsed = Number(normalized);
  if (!Number.isFinite(parsed)) {
    return "";
  }
  if (parsed > max) {
    return String(max);
  }
  if (parsed < min) {
    return String(min);
  }
  return normalized;
}

function optionalBoundedInteger(value: string, min: number, max: number): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    return undefined;
  }
  return parsed;
}

function optionalBoundedNumber(value: string, min: number, max: number): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) {
    return undefined;
  }
  return parsed;
}

function messageFromError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}
