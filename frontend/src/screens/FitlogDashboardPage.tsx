"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import * as fitlogApi from "@/api/fitlog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { todayString } from "@/lib/date";
import type { DailyReport, GoalProfile, StrategyResponse } from "@/types";

export default function FitlogDashboardPage() {
  const [goal, setGoal] = useState<GoalProfile | null>(null);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [strategy, setStrategy] = useState<StrategyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const today = todayString();

  useEffect(() => {
    fitlogApi.getGoal().then(setGoal).catch(() => setGoal(null));
    fitlogApi.getDailyReport(today).then(setReport).catch((err) => setError(err instanceof Error ? err.message : "Failed to load report"));
  }, [today]);

  const createStrategy = async () => {
    setStrategy(await fitlogApi.createStrategy({ date: today, question: "오늘 목표 달성을 위해 무엇을 조정해야 하나요?" }));
  };

  return (
    <section className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-extrabold">FitLog</h1>
          <p className="text-sm text-muted-foreground">Goal-based meal strategy coach</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild><Link href="/fitlog/meals/new">Add meal</Link></Button>
          <Button asChild variant="outline"><Link href={`/fitlog/meals?date=${today}`}>Meals</Link></Button>
          <Button asChild variant="outline"><Link href={`/fitlog/strategies?date=${today}`}>Strategies</Link></Button>
          <Button asChild variant="outline"><Link href="/fitlog/goal">Goal</Link></Button>
        </div>
      </div>
      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Goal</CardTitle></CardHeader>
          <CardContent>
            {goal ? (
              <p className="text-sm">{goal.current_weight_kg}kg to {goal.target_weight_kg}kg by {goal.target_date}</p>
            ) : (
              <Button asChild variant="outline"><Link href="/fitlog/goal">Set goal</Link></Button>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Today</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>{report?.total_calories ?? 0} kcal logged</p>
            <p>{report?.remaining_calories ?? "-"} kcal remaining</p>
            <p>{report?.meal_count ?? 0} meals</p>
            <Button asChild variant="outline" size="sm" className="mt-2">
              <Link href={`/fitlog/meals?date=${today}`}>오늘 먹은 것 보기</Link>
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Coach</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Button type="button" variant="outline" onClick={createStrategy}>Generate strategy</Button>
            <Button asChild variant="outline" size="sm">
              <Link href={`/fitlog/strategies?date=${today}`}>전략 기록 보기</Link>
            </Button>
            {strategy ? <p className="text-sm">{strategy.summary}</p> : null}
            {strategy?.agent_steps?.length ? (
              <p className="text-xs text-muted-foreground">Agent tools: {strategy.agent_steps.map((step) => step.tool).join(" -> ")}</p>
            ) : null}
          </CardContent>
        </Card>
      </div>
      {report?.warnings.length ? (
        <Card>
          <CardHeader><CardTitle>Warnings</CardTitle></CardHeader>
          <CardContent>
            <ul className="list-disc pl-5 text-sm">
              {report.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </section>
  );
}
