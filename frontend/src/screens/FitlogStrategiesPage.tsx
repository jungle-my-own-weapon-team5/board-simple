"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import * as fitlogApi from "@/api/fitlog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { todayString } from "@/lib/date";
import type { StrategyAdvice } from "@/types";

export default function FitlogStrategiesPage() {
  const params = useSearchParams();
  const [date, setDate] = useState(params.get("date") ?? todayString());
  const [items, setItems] = useState<StrategyAdvice[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    fitlogApi
      .listStrategies(date)
      .then((data) => setItems(data.items))
      .catch((err) => setError(err instanceof Error ? err.message : "전략 기록을 불러오지 못했습니다."));
  }, [date]);

  return (
    <section className="grid gap-5">
      <div>
        <h1 className="text-3xl font-extrabold">전략 기록</h1>
        <p className="text-sm text-muted-foreground">생성된 코치 전략을 날짜별로 다시 확인합니다.</p>
      </div>
      <label className="grid max-w-64 gap-2 text-sm font-semibold">
        날짜
        <Input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
      </label>
      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      <div className="grid gap-3">
        {items.length === 0 ? (
          <Card>
            <CardContent className="p-5 text-sm text-muted-foreground">
              이 날짜에 생성된 전략이 없습니다. Coach에서 전략을 생성해 주세요.
            </CardContent>
          </Card>
        ) : null}
        {items.map((item) => (
          <Card key={item.id}>
            <CardHeader>
              <CardTitle className="text-lg">{item.pace_status} · {new Date(item.created_at).toLocaleString()}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              {item.question ? <p className="text-muted-foreground">질문: {item.question}</p> : null}
              <p>{item.summary}</p>
              <p><strong>오늘:</strong> {item.today_strategy}</p>
              <p><strong>내일:</strong> {item.tomorrow_strategy}</p>
              {item.rag_evidence.map((evidence) => (
                <blockquote key={`${item.id}-${evidence.title}`} className="border-l-2 pl-3 text-muted-foreground">
                  {evidence.title}: {evidence.snippet}
                </blockquote>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
