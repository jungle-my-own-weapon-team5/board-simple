"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import * as fitlogApi from "@/api/fitlog";
import { assetUrl } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { MealLog } from "@/types";

const mealTypeLabels: Record<MealLog["meal_type"], string> = {
  breakfast: "아침",
  lunch: "점심",
  dinner: "저녁",
  snack: "간식",
};

export default function FitlogMealDetailPage() {
  const router = useRouter();
  const params = useParams<{ mealId: string }>();
  const mealId = Number(params.mealId);
  const [meal, setMeal] = useState<MealLog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fitlogApi
      .getMeal(mealId)
      .then(setMeal)
      .catch((err) => setError(err instanceof Error ? err.message : "식단 기록을 불러오지 못했습니다."));
  }, [mealId]);

  const remove = async () => {
    await fitlogApi.deleteMeal(mealId);
    router.push("/fitlog/meals");
  };

  if (error) return <p className="font-semibold text-destructive">{error}</p>;
  if (!meal) return <p className="text-muted-foreground">불러오는 중...</p>;

  return (
    <section className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-extrabold">
          {mealTypeLabels[meal.meal_type]} · {meal.meal_date}
        </h1>
        <div className="flex gap-2">
          <Button asChild variant="outline">
            <Link href={`/fitlog/meals/${meal.id}/edit`}>수정</Link>
          </Button>
          <Button type="button" variant="destructive" onClick={remove}>
            삭제
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>영양 요약</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-4">
          <p>{meal.total_calories} kcal</p>
          <p>탄수화물 {meal.carbs_g}g</p>
          <p>단백질 {meal.protein_g}g</p>
          <p>지방 {meal.fat_g}g</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>음식</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2">
          {meal.foods.map((food) => (
            <div key={food.id} className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 rounded-md border p-3 text-sm">
              {food.image_path ? (
                <img src={assetUrl(food.image_path)} alt="" className="h-16 w-16 rounded-md border object-cover" />
              ) : (
                <div className="h-16 w-16 rounded-md border bg-muted/10" />
              )}
              <div className="grid gap-1">
                <strong>{food.name}</strong>
                <span className="text-xs text-muted-foreground">{food.portion_text || "1인분"}</span>
                <span>
                  {food.calories} kcal · 탄 {food.carbs_g}g · 단 {food.protein_g}g · 지 {food.fat_g}g
                </span>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}
