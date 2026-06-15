"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as fitlogApi from "@/api/fitlog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function FitlogGoalPage() {
  const router = useRouter();
  const [current, setCurrent] = useState("78");
  const [target, setTarget] = useState("70");
  const [date, setDate] = useState(new Date(Date.now() + 1000 * 60 * 60 * 24 * 90).toISOString().slice(0, 10));
  const [calories, setCalories] = useState("1800");
  const [activity, setActivity] = useState<"low" | "moderate" | "high">("moderate");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fitlogApi.getGoal().then((goal) => {
      setCurrent(String(goal.current_weight_kg));
      setTarget(String(goal.target_weight_kg));
      setDate(goal.target_date);
      setCalories(String(goal.daily_calorie_target));
      setActivity(goal.activity_level);
    }).catch(() => undefined);
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await fitlogApi.saveGoal({
        current_weight_kg: Number(current),
        target_weight_kg: Number(target),
        target_date: date,
        daily_calorie_target: Number(calories),
        activity_level: activity,
      });
      router.push("/fitlog");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save goal");
    }
  };

  return (
    <section className="mx-auto max-w-xl">
      <Card>
        <CardHeader><CardTitle>Goal</CardTitle></CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={submit}>
            <label className="grid gap-2 text-sm font-semibold">Current weight kg<Input type="number" step="0.1" value={current} onChange={(e) => setCurrent(e.target.value)} required /></label>
            <label className="grid gap-2 text-sm font-semibold">Target weight kg<Input type="number" step="0.1" value={target} onChange={(e) => setTarget(e.target.value)} required /></label>
            <label className="grid gap-2 text-sm font-semibold">Target date<Input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
            <label className="grid gap-2 text-sm font-semibold">Daily calorie target<Input type="number" value={calories} onChange={(e) => setCalories(e.target.value)} required /></label>
            <label className="grid gap-2 text-sm font-semibold">Activity
              <select className="h-10 rounded-md border bg-background px-3" value={activity} onChange={(e) => setActivity(e.target.value as "low" | "moderate" | "high")}>
                <option value="low">Low</option>
                <option value="moderate">Moderate</option>
                <option value="high">High</option>
              </select>
            </label>
            {error ? <p className="font-semibold text-destructive">{error}</p> : null}
            <Button type="submit">Save goal</Button>
          </form>
        </CardContent>
      </Card>
    </section>
  );
}
