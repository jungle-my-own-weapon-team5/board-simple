"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import * as fitlogApi from "@/api/fitlog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { todayString } from "@/lib/date";
import type { DailyReport } from "@/types";

export default function FitlogReportPage() {
  const params = useSearchParams();
  const date = params.get("date") ?? todayString();
  const [report, setReport] = useState<DailyReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fitlogApi.getDailyReport(date).then(setReport).catch((err) => setError(err instanceof Error ? err.message : "Failed to load report"));
  }, [date]);

  if (error) return <p className="font-semibold text-destructive">{error}</p>;
  if (!report) return <p className="text-muted-foreground">Loading...</p>;

  return (
    <section className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-extrabold">Daily report</h1>
        <div className="flex gap-2">
          <Button asChild><Link href="/fitlog/meals/new">Add meal</Link></Button>
          <Button asChild variant="outline"><Link href={`/fitlog/meals?date=${date}`}>Meals</Link></Button>
        </div>
      </div>
      <Card>
        <CardHeader><CardTitle>{report.date}</CardTitle></CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-4">
          <p>{report.total_calories} kcal</p><p>{report.remaining_calories ?? "-"} kcal remaining</p><p>C {report.carbs_g}g</p><p>P {report.protein_g}g · F {report.fat_g}g</p>
        </CardContent>
      </Card>
      {report.warnings.length ? <Card><CardHeader><CardTitle>Warnings</CardTitle></CardHeader><CardContent><ul className="list-disc pl-5 text-sm">{report.warnings.map((item) => <li key={item}>{item}</li>)}</ul></CardContent></Card> : null}
      <Card>
        <CardHeader><CardTitle>Meals</CardTitle></CardHeader>
        <CardContent className="grid gap-2">
          {report.meals.map((meal) => (
            <Link key={meal.id} href={`/fitlog/meals/${meal.id}`} className="rounded-md border p-3 text-sm hover:bg-accent">
              {meal.meal_type}: {meal.total_calories} kcal
            </Link>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}
