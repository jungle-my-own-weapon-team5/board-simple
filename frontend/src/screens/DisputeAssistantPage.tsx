"use client";

import {
  FileText,
  Gavel,
  Loader2,
  ListChecks,
  Search,
  SlidersHorizontal
} from "lucide-react";
import { useMemo, useState } from "react";
import type { ComponentProps, FormEvent, ReactNode } from "react";

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

const DOCUMENT_TYPE_OPTIONS: Array<{ value: LegalDocumentType | ""; label: string }> = [
  { value: "", label: "전체" },
  { value: "statute", label: "법령" },
  { value: "case", label: "판례" },
  { value: "interpretation", label: "해석례" },
  { value: "admin_appeal", label: "행정심판" },
  { value: "user_file", label: "사용자 문서" },
  { value: "memo", label: "메모" }
];

type GeneratedBlockTitle = "쟁점 정리" | "답변 초안";

const GENERATED_EMPTY_TEXT: Record<GeneratedBlockTitle, string> = {
  "쟁점 정리": "쟁점 정리를 실행하면 결과가 표시됩니다.",
  "답변 초안": "답변 초안을 실행하면 결과가 표시됩니다."
};

const DEFAULT_FACTS =
  "임대차 계약이 종료되었지만 임대인이 보증금을 반환하지 않고 있습니다.";
const DEFAULT_QUESTION = "검토해야 할 쟁점과 답변 초안 방향을 알려주세요.";

type ActionState = "idle" | "searching" | "issues" | "draft";

export default function DisputeAssistantPage() {
  // 입력값과 실행 결과를 분리해 검색 결과를 보존한 상태에서 초안만 다시 생성할 수 있게 합니다.
  const [facts, setFacts] = useState(DEFAULT_FACTS);
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [searchMode, setSearchMode] = useState<RagSearchMode>("issue_spotting");
  const [documentType, setDocumentType] = useState<LegalDocumentType | "">("");
  const [topK, setTopK] = useState("8");
  const [maxChunksPerDocument, setMaxChunksPerDocument] = useState("5");
  const [scoreThreshold, setScoreThreshold] = useState("");
  const [searchResult, setSearchResult] = useState<RagSearchResponse | null>(null);
  const [issuesResult, setIssuesResult] = useState<DisputeIssuesResponse | null>(null);
  const [draftResult, setDraftResult] = useState<AnswerDraftResponse | null>(null);
  const [activeAction, setActiveAction] = useState<ActionState>("idle");
  const [error, setError] = useState<string | null>(null);

  const trimmedFacts = facts.trim();
  const trimmedQuestion = question.trim();
  const isBusy = activeAction !== "idle";
  const isRunnable = trimmedFacts.length > 0 && trimmedQuestion.length > 0 && !isBusy;
  const retrievalOptions = useMemo(
    () => ({
      search_mode: searchMode,
      top_k: optionalPositiveNumber(topK),
      score_threshold: optionalNumber(scoreThreshold),
      max_chunks_per_document: optionalPositiveNumber(maxChunksPerDocument)
    }),
    [maxChunksPerDocument, scoreThreshold, searchMode, topK]
  );

  // 자료 검색은 답변 생성을 하지 않고 backend retrieval 결과만 받아옵니다.
  const handleSearch = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!isRunnable) {
      return;
    }

    setError(null);
    setActiveAction("searching");
    try {
      const result = await ragApi.searchRagDocuments({
        query: `${trimmedFacts}\n${trimmedQuestion}`,
        ...retrievalOptions,
        filters: documentType ? { document_type: documentType } : undefined
      });
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
      const result = await aiApi.createDisputeIssues({
        facts: trimmedFacts,
        question: trimmedQuestion,
        ...retrievalOptions
      });
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
        facts: trimmedFacts,
        question: trimmedQuestion,
        tone: "formal",
        ...retrievalOptions
      });
      setDraftResult(result);
    } catch (err) {
      setError(messageFromError(err, "답변 초안 생성에 실패했습니다."));
    } finally {
      setActiveAction("idle");
    }
  };

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Gavel className="size-7 text-primary" />
          <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">
            분쟁 보조
          </h1>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          사실관계와 질문을 기준으로 내부 RAG 검색, 쟁점 정리, 답변 초안을 실행합니다.
        </p>
      </div>

      <form className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]" onSubmit={handleSearch}>
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
                className="min-h-40 resize-y"
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
            <div className="flex flex-wrap gap-2">
              <ActionButton
                icon={<Search />}
                isLoading={activeAction === "searching"}
                disabled={!isRunnable}
                type="submit"
              >
                자료 검색
              </ActionButton>
              <ActionButton
                icon={<ListChecks />}
                isLoading={activeAction === "issues"}
                disabled={!isRunnable}
                type="button"
                onClick={handleIssues}
                variant="outline"
              >
                쟁점 정리
              </ActionButton>
              <ActionButton
                icon={<FileText />}
                isLoading={activeAction === "draft"}
                disabled={!isRunnable}
                type="button"
                onClick={handleDraft}
                variant="secondary"
              >
                답변 초안
              </ActionButton>
            </div>
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
            <label className="grid gap-2 text-sm font-semibold">
              문서 유형
              <select
                value={documentType}
                onChange={(event) => setDocumentType(event.target.value as LegalDocumentType | "")}
                className="h-10 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {DOCUMENT_TYPE_OPTIONS.map((option) => (
                  <option value={option.value} key={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <NumberField label="Top K" value={topK} onChange={setTopK} min={1} max={100} />
            <NumberField
              label="문서당 청크"
              value={maxChunksPerDocument}
              onChange={setMaxChunksPerDocument}
              min={1}
              max={100}
            />
            <label className="grid gap-2 text-sm font-semibold">
              Score Threshold
              <Input
                type="number"
                value={scoreThreshold}
                onChange={(event) => setScoreThreshold(event.target.value)}
                inputMode="decimal"
                min={0}
                max={1}
                step={0.01}
                placeholder="선택"
              />
            </label>
          </CardContent>
        </Card>
      </form>

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <SearchResultsPanel result={searchResult} />
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
  max
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min: number;
  max: number;
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
      />
    </label>
  );
}

function SearchResultsPanel({ result }: { result: RagSearchResponse | null }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-lg">검색 결과</CardTitle>
          {result ? (
            <Badge variant="secondary">
              Run #{result.run_id} · {result.items.length}건
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="grid gap-3">
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
    <article className="rounded-md border border-border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-extrabold [overflow-wrap:anywhere]">{item.title}</h3>
          <p className="text-sm text-muted-foreground">
            {item.heading || "제목 없음"} · 점수 {item.score.toFixed(3)}
          </p>
        </div>
        <Badge variant="outline">#{item.rank}</Badge>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">
        {item.content}
      </p>
      {item.source_url ? (
        <a
          href={item.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-3 inline-block text-sm font-semibold text-primary hover:underline"
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
    <div className="grid gap-4">
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
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-lg">{title}</CardTitle>
          {runId ? <Badge variant="secondary">Run #{runId}</Badge> : null}
        </div>
      </CardHeader>
      <CardContent className="grid gap-3">
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

function optionalPositiveNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return undefined;
  }
  return parsed;
}

function optionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
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
