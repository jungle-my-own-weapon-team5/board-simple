"use client";

import { FormEvent, useState } from "react";
import * as aiApi from "../api/ai";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import type { AgentRunResponse, ExternalSearchResponse, RagSearchResponse } from "../types";

export default function AiPlaygroundPage() {
  const [query, setQuery] = useState("세조와 단종");
  const [rag, setRag] = useState<RagSearchResponse | null>(null);
  const [external, setExternal] = useState<ExternalSearchResponse | null>(null);
  const [agent, setAgent] = useState<AgentRunResponse | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const [ragResult, externalResult, agentResult] = await Promise.all([
      aiApi.searchRag({ query, top_k: 3 }),
      aiApi.searchExternal({ keyword: query }),
      aiApi.runAgent({ goal: "근거와 토론 질문 만들기", topic: query })
    ]);
    setRag(ragResult);
    setExternal(externalResult);
    setAgent(agentResult);
  };

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">AI Playground</h1>
        <p className="text-sm text-muted-foreground">RAG 검색, 외부 자료 호출, Agent 실행 로그를 한 번에 확인합니다.</p>
      </div>
      <form className="flex flex-col gap-2 md:flex-row" onSubmit={handleSubmit}>
        <Input value={query} onChange={(event) => setQuery(event.target.value)} />
        <Button type="submit">실행</Button>
      </form>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 font-extrabold">RAG 검색</h2>
            <p className="text-sm text-muted-foreground">{rag?.answer_summary ?? "아직 실행 전입니다."}</p>
            <div className="mt-3 flex flex-col gap-2">
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
