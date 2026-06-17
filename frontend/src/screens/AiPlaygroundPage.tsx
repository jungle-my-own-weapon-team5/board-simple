"use client";

import { ExternalLink } from "lucide-react";
import { FormEvent, useState } from "react";
import Link from "next/link";
import * as aiApi from "../api/ai";
import { ApiError } from "../api/client";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import type {
  AgentRunResponse,
  ExternalSearchResponse,
  RagCorpusMode,
  RagQualityAgentResponse,
  RagSearchResponse
} from "../types";
import { useAuthStore } from "../stores/authStore";

function aiErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return error.message;
    }
    return `${error.status}: ${error.message}`;
  }
  return error instanceof Error ? error.message : "AI 요청을 처리하지 못했습니다.";
}

export default function AiPlaygroundPage() {
  const { user } = useAuthStore();
  const [query, setQuery] = useState("세조와 단종");
  const [corpus, setCorpus] = useState<RagCorpusMode>("auto");
  const [rag, setRag] = useState<RagSearchResponse | null>(null);
  const [ragAgent, setRagAgent] = useState<RagQualityAgentResponse | null>(null);
  const [external, setExternal] = useState<ExternalSearchResponse | null>(null);
  const [agent, setAgent] = useState<AgentRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!user?.is_admin) {
    return (
      <section className="mx-auto flex max-w-lg flex-col gap-4 border border-border bg-card p-6">
        <h1 className="font-serif-display text-3xl font-bold leading-[1.35] sm:text-4xl">관리자 전용</h1>
        <p className="text-sm leading-6 text-muted-foreground">
          AI 실험실은 RAG, 외부 자료, 실행 로그를 점검하는 관리자 도구입니다.
        </p>
        <Button asChild className="w-fit rounded-sm">
          <Link href="/">홈으로 이동</Link>
        </Button>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    const [ragResult, ragAgentResult, externalResult, agentResult] = await Promise.allSettled([
      aiApi.searchRag({ query, top_k: 3, corpus }),
      aiApi.searchRagWithAgent({ query, top_k: 3, corpus }),
      aiApi.searchExternal({ keyword: query }),
      aiApi.runAgent({ goal: "근거와 토론 질문 만들기", topic: query })
    ]);
    setIsSubmitting(false);

    const failures = [ragResult, ragAgentResult, externalResult, agentResult]
      .filter((result): result is PromiseRejectedResult => result.status === "rejected")
      .map((result) => aiErrorMessage(result.reason));

    if (ragResult.status === "fulfilled") {
      setRag(ragResult.value);
    }
    if (ragAgentResult.status === "fulfilled") {
      setRagAgent(ragAgentResult.value);
    }
    if (externalResult.status === "fulfilled") {
      setExternal(externalResult.value);
    }
    if (agentResult.status === "fulfilled") {
      setAgent(agentResult.value);
    }
    if (failures.length > 0) {
      setError(`일부 AI 요청이 실패했습니다. ${failures[0]}`);
    }
  };

  return (
    <section className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <header className="border-b border-border/70 pb-5">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">AI Operations</p>
        <h1 className="font-serif-display text-3xl font-bold leading-[1.35] sm:text-4xl">AI 실험실</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">RAG 검색, 외부 자료 호출, 실행 로그를 한 번에 확인합니다.</p>
      </header>
      <form className="bal-card relative flex flex-col gap-2 overflow-hidden border border-border bg-card p-4 md:grid md:grid-cols-[minmax(0,1fr)_220px_auto]" onSubmit={handleSubmit}>
        <Input className="rounded-sm" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select
          className="h-10 rounded-sm border border-input bg-background px-3 text-sm font-medium"
          value={corpus}
          onChange={(event) => setCorpus(event.target.value as RagCorpusMode)}
        >
          <option value="auto">auto</option>
          <option value="encykorea">encykorea</option>
          <option value="legacy">legacy</option>
          <option value="sinpyeon_hanguksa">sinpyeon_hanguksa</option>
          <option value="sillok-v2">sillok-v2</option>
          <option value="all">all</option>
        </select>
        <Button type="submit" className="rounded-sm" disabled={isSubmitting}>{isSubmitting ? "실행 중" : "실행"}</Button>
      </form>
      {error ? <p className="text-sm font-semibold text-destructive">{error}</p> : null}
      <div className="grid gap-4 xl:grid-cols-4">
        <Card className="bal-card relative overflow-hidden rounded-sm">
          <CardContent className="p-4">
            <h2 className="font-serif-display mb-3 font-bold">RAG 검색</h2>
            {rag ? (
              <p className="mb-2 text-xs font-semibold text-muted-foreground">
                검색 corpus: {rag.searched_corpora.join(" → ")}
              </p>
            ) : null}
            {rag?.weak_evidence ? (
              <p className="mb-2 text-xs font-semibold text-destructive">기준치 이상의 내부 근거가 부족합니다.</p>
            ) : null}
            <p className="text-sm leading-6 text-muted-foreground">{rag?.answer_summary ?? "아직 실행 전입니다."}</p>
            <div className="mt-3 flex flex-col gap-2">
              {rag && rag.citations.length === 0 ? (
                <p className="border-t border-border pt-2 text-sm text-muted-foreground">
                  관련도 cutoff를 통과한 citation이 없습니다.
                </p>
              ) : null}
              {rag?.citations.map((item) => (
                <div key={item.id} className="border-t border-border pt-2 text-sm">
                  <p className="font-bold">{item.title}</p>
                  <p className="text-muted-foreground">{item.period} · 관련도 {item.relevance}</p>
                  <p className="mt-1 leading-6">{item.summary}</p>
                  {item.source_url ? (
                    <Button asChild variant="outline" size="sm" className="mt-2 rounded-sm">
                      <a href={item.source_url} target="_blank" rel="noreferrer">
                        <ExternalLink />
                        <span>근거 원문</span>
                      </a>
                    </Button>
                  ) : null}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card className="bal-card relative overflow-hidden rounded-sm">
          <CardContent className="p-4">
            <h2 className="font-serif-display mb-3 font-bold">RAG 품질 점검</h2>
            {ragAgent ? (
              <p className="mb-2 text-xs font-semibold text-muted-foreground">
                검색 corpus: {ragAgent.searched_corpora.join(" → ")}
              </p>
            ) : null}
            {ragAgent?.weak_evidence ? (
              <p className="mb-2 text-xs font-semibold text-destructive">외부 검색 보강이 필요합니다.</p>
            ) : null}
            <p className="text-sm leading-6 text-muted-foreground">
              {ragAgent?.answer_summary ?? "아직 실행 전입니다."}
            </p>
            {ragAgent ? (
              <div className="mt-3 flex flex-col gap-2">
                <p className="text-xs font-semibold text-muted-foreground">
                  최종 질의: {ragAgent.final_query}
                </p>
                {ragAgent.attempts.map((attempt) => (
                  <div key={attempt.query} className="border-t border-border pt-2 text-sm">
                    <p className="font-bold leading-6">{attempt.query}</p>
                    <p className="leading-6 text-muted-foreground">
                      {attempt.decision} · citation {attempt.citation_count} · 최고 관련도 {attempt.max_relevance}
                    </p>
                  </div>
                ))}
                {ragAgent.suggested_external_keywords.length > 0 ? (
                  <p className="border-t border-border pt-2 text-xs text-muted-foreground">
                    외부 검색어: {ragAgent.suggested_external_keywords.join(", ")}
                  </p>
                ) : null}
                {ragAgent.citations.length > 0 ? (
                  <div className="border-t border-border pt-2">
                    <p className="mb-2 text-sm font-bold">최종 근거 원문</p>
                    <div className="flex flex-col gap-2">
                      {ragAgent.citations.map((item) => (
                        <div key={item.id} className="rounded-sm border border-border bg-background p-2 text-sm">
                          <p className="font-semibold">{item.title}</p>
                          <p className="text-xs text-muted-foreground">{item.period} · 관련도 {item.relevance}</p>
                          {item.source_url ? (
                            <Button asChild variant="outline" size="sm" className="mt-2 rounded-sm">
                              <a href={item.source_url} target="_blank" rel="noreferrer">
                                <ExternalLink />
                                <span>근거 원문</span>
                              </a>
                            </Button>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
        <Card className="bal-card relative overflow-hidden rounded-sm">
          <CardContent className="p-4">
            <h2 className="font-serif-display mb-3 font-bold">외부 자료</h2>
            {!external ? <p className="text-sm text-muted-foreground">아직 실행 전입니다.</p> : null}
            {external && external.resources.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                조선왕조실록에서 표시할 수 있는 외부 기사 링크를 찾지 못했습니다.
              </p>
            ) : null}
            {external?.resources.map((item) => (
              <a
                key={`${item.provider}-${item.url}`}
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-sm border border-border bg-background p-2 text-sm transition-colors hover:bg-accent"
              >
                <span className="block font-bold">{item.title}</span>
                <span className="block text-muted-foreground">{item.provider}</span>
                <span className="block leading-6">{item.description}</span>
              </a>
            ))}
            {external ? <p className="mt-3 text-xs text-muted-foreground">{external.tool_log.tool} · {external.tool_log.status}</p> : null}
          </CardContent>
        </Card>
        <Card className="bal-card relative overflow-hidden rounded-sm">
          <CardContent className="p-4">
            <h2 className="font-serif-display mb-3 font-bold">실행 로그</h2>
            <div className="flex flex-col gap-2">
              {agent?.steps.map((step) => (
                <div key={step.name} className="text-sm">
                  <p className="font-bold">{step.name}</p>
                  <p className="leading-6 text-muted-foreground">{step.output}</p>
                </div>
              )) ?? <p className="text-sm text-muted-foreground">아직 실행 전입니다.</p>}
            </div>
            {agent ? <p className="mt-3 text-sm font-semibold">{agent.final_answer}</p> : null}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
