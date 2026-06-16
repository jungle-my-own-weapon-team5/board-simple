"use client";

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
  const [rag, setRag] = useState<RagSearchResponse | null>(null);
  const [ragAgent, setRagAgent] = useState<RagQualityAgentResponse | null>(null);
  const [external, setExternal] = useState<ExternalSearchResponse | null>(null);
  const [agent, setAgent] = useState<AgentRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!user?.is_admin) {
    return (
      <section className="mx-auto flex max-w-lg flex-col gap-4">
        <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">관리자 전용</h1>
        <p className="text-sm text-muted-foreground">
          AI Playground는 RAG, 외부 자료, Agent 로그를 점검하는 관리자 도구입니다.
        </p>
        <Button asChild className="w-fit">
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
      aiApi.searchRag({ query, top_k: 3 }),
      aiApi.searchRagWithAgent({ query, top_k: 3 }),
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
    <section className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">AI Playground</h1>
        <p className="text-sm text-muted-foreground">RAG 검색, 외부 자료 호출, Agent 실행 로그를 한 번에 확인합니다.</p>
      </div>
      <form className="flex flex-col gap-2 md:flex-row" onSubmit={handleSubmit}>
        <Input value={query} onChange={(event) => setQuery(event.target.value)} />
        <Button type="submit" disabled={isSubmitting}>{isSubmitting ? "실행 중" : "실행"}</Button>
      </form>
      {error ? <p className="text-sm font-semibold text-destructive">{error}</p> : null}
      <div className="grid gap-4 xl:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 font-extrabold">RAG 검색</h2>
            {rag?.weak_evidence ? (
              <p className="mb-2 text-xs font-semibold text-destructive">기준치 이상의 내부 근거가 부족합니다.</p>
            ) : null}
            <p className="text-sm text-muted-foreground">{rag?.answer_summary ?? "아직 실행 전입니다."}</p>
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
                  <p>{item.summary}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 font-extrabold">RAG 품질 Agent</h2>
            {ragAgent?.weak_evidence ? (
              <p className="mb-2 text-xs font-semibold text-destructive">외부 검색 보강이 필요합니다.</p>
            ) : null}
            <p className="text-sm text-muted-foreground">
              {ragAgent?.answer_summary ?? "아직 실행 전입니다."}
            </p>
            {ragAgent ? (
              <div className="mt-3 flex flex-col gap-2">
                <p className="text-xs font-semibold text-muted-foreground">
                  최종 질의: {ragAgent.final_query}
                </p>
                {ragAgent.attempts.map((attempt) => (
                  <div key={attempt.query} className="border-t border-border pt-2 text-sm">
                    <p className="font-bold">{attempt.query}</p>
                    <p className="text-muted-foreground">
                      {attempt.decision} · citation {attempt.citation_count} · 최고 관련도 {attempt.max_relevance}
                    </p>
                  </div>
                ))}
                {ragAgent.suggested_external_keywords.length > 0 ? (
                  <p className="border-t border-border pt-2 text-xs text-muted-foreground">
                    외부 검색어: {ragAgent.suggested_external_keywords.join(", ")}
                  </p>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 font-extrabold">외부 자료</h2>
            {external?.resources.map((item) => (
              <div key={item.title} className="text-sm">
                <p className="font-bold">{item.title}</p>
                <p className="text-muted-foreground">{item.provider}</p>
                <p>{item.description}</p>
              </div>
            )) ?? <p className="text-sm text-muted-foreground">아직 실행 전입니다.</p>}
            {external ? <p className="mt-3 text-xs text-muted-foreground">{external.tool_log.tool} · {external.tool_log.status}</p> : null}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 font-extrabold">Agent 로그</h2>
            <div className="flex flex-col gap-2">
              {agent?.steps.map((step) => (
                <div key={step.name} className="text-sm">
                  <p className="font-bold">{step.name}</p>
                  <p className="text-muted-foreground">{step.output}</p>
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
