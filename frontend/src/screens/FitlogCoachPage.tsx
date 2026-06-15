"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import * as fitlogApi from "@/api/fitlog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { todayString } from "@/lib/date";
import type { StrategyResponse } from "@/types";

export default function FitlogCoachPage() {
  const [date, setDate] = useState(todayString());
  const [question, setQuestion] = useState("오늘 저녁은 어떻게 먹는 게 좋을까?");
  const [answer, setAnswer] = useState<StrategyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      setAnswer(await fitlogApi.createStrategy({ date, question }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create strategy");
    }
  };

  return (
    <section className="grid gap-5">
      <h1 className="text-3xl font-extrabold">Coach</h1>
      <form className="grid gap-3 md:grid-cols-[180px_1fr_auto]" onSubmit={submit}>
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <Input value={question} onChange={(e) => setQuestion(e.target.value)} />
        <Button type="submit">Ask</Button>
      </form>
      <Button asChild variant="outline" className="w-fit">
        <Link href={`/fitlog/strategies?date=${date}`}>전략 기록 보기</Link>
      </Button>
      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      {answer ? (
        <Card>
          <CardHeader><CardTitle>{answer.pace_status}</CardTitle></CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <p>{answer.summary}</p>
            <p><strong>Today:</strong> {answer.today_strategy}</p>
            <p><strong>Tomorrow:</strong> {answer.tomorrow_strategy}</p>
            <ul className="list-disc pl-5">{answer.risk_notes.map((note) => <li key={note}>{note}</li>)}</ul>
            {answer.rag_evidence.map((item) => <blockquote key={item.title} className="border-l-2 pl-3 text-muted-foreground">{item.title}: {item.snippet}</blockquote>)}
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}
