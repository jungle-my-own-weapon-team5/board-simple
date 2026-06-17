"use client";

import { FormEvent, useState } from "react";
import { MessageCircle, Send, X } from "lucide-react";
import * as fitlogApi from "@/api/fitlog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { todayString } from "@/lib/date";
import type { StrategyResponse } from "@/types";

export default function FitlogCoachButton() {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(todayString());
  const [question, setQuestion] = useState("오늘 목표 달성을 위해 무엇을 조정해야 하나요?");
  const [answer, setAnswer] = useState<StrategyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      setAnswer(await fitlogApi.createStrategy({ date, question }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "전략을 생성하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {open ? (
        <section
          aria-label="FitLog Coach"
          className="fixed bottom-20 right-5 z-50 grid max-h-[min(680px,calc(100vh-7rem))] w-[min(380px,calc(100vw-2rem))] gap-3 overflow-y-auto rounded-lg border bg-background p-4 shadow-xl"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold">Coach</h2>
              <p className="text-xs text-muted-foreground">FitLog Diet Strategy Agent</p>
            </div>
            <Button type="button" variant="ghost" size="icon" aria-label="Coach 닫기" onClick={() => setOpen(false)}>
              <X className="h-4 w-4" />
            </Button>
          </div>

          <form className="grid gap-3" onSubmit={submit}>
            <label className="grid gap-1 text-xs font-semibold">
              날짜
              <Input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs font-semibold">
              질문
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                className="min-h-20 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <Button type="submit" disabled={loading || !question.trim()}>
              <Send className="h-4 w-4" />
              {loading ? "생성 중" : "전략 생성"}
            </Button>
          </form>

          {error ? <p className="text-sm font-semibold text-destructive">{error}</p> : null}
          {answer ? (
            <div className="grid gap-3 border-t pt-3 text-sm">
              <p className="font-semibold">{answer.pace_status}</p>
              <p>{answer.summary}</p>
              <p><strong>오늘:</strong> {answer.today_strategy}</p>
              <p><strong>내일:</strong> {answer.tomorrow_strategy}</p>
              {answer.agent_steps?.length ? (
                <div className="rounded-md border p-3">
                  <p className="font-semibold">Agent 실행 단계</p>
                  <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground">
                    {answer.agent_steps.map((step, index) => (
                      <li key={`${step.tool}-${index}`}>{step.tool}</li>
                    ))}
                  </ol>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      <Button
        type="button"
        size="icon"
        aria-label={open ? "Coach 닫기" : "Coach 열기"}
        title={open ? "Coach 닫기" : "Coach 열기"}
        className="fixed bottom-5 right-5 z-50 h-12 w-12 rounded-full shadow-lg"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <X className="h-5 w-5" aria-hidden="true" /> : <MessageCircle className="h-5 w-5" aria-hidden="true" />}
      </Button>
    </>
  );
}
