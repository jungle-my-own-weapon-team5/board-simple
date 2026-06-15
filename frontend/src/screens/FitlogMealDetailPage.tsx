"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import * as fitlogApi from "@/api/fitlog";
import { assetUrl } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { MealLog } from "@/types";

export default function FitlogMealDetailPage() {
  const router = useRouter();
  const params = useParams<{ mealId: string }>();
  const mealId = Number(params.mealId);
  const [meal, setMeal] = useState<MealLog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fitlogApi.getMeal(mealId).then(setMeal).catch((err) => setError(err instanceof Error ? err.message : "Failed to load meal"));
  }, [mealId]);

  const remove = async () => {
    await fitlogApi.deleteMeal(mealId);
    router.push("/fitlog");
  };

  if (error) return <p className="font-semibold text-destructive">{error}</p>;
  if (!meal) return <p className="text-muted-foreground">Loading...</p>;

  return (
    <section className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-extrabold">{meal.meal_type} · {meal.meal_date}</h1>
        <div className="flex gap-2">
          <Button asChild variant="outline"><Link href={`/fitlog/meals/${meal.id}/edit`}>Edit</Link></Button>
          <Button type="button" variant="destructive" onClick={remove}>Delete</Button>
        </div>
      </div>
      <Card>
        <CardHeader><CardTitle>Nutrition</CardTitle></CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-4">
          <p>{meal.total_calories} kcal</p><p>{meal.carbs_g}g carbs</p><p>{meal.protein_g}g protein</p><p>{meal.fat_g}g fat</p>
        </CardContent>
      </Card>
      {(meal.image_path || meal.crop_image_path) ? (
        <Card>
          <CardHeader><CardTitle>Images</CardTitle></CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {meal.image_path ? <img src={assetUrl(meal.image_path)} alt="" className="max-h-80 rounded-md border object-contain" /> : null}
            {meal.crop_image_path ? <img src={assetUrl(meal.crop_image_path)} alt="" className="max-h-80 rounded-md border object-contain" /> : null}
          </CardContent>
        </Card>
      ) : null}
      <Card>
        <CardHeader><CardTitle>Foods</CardTitle></CardHeader>
        <CardContent className="grid gap-2">
          {meal.foods.map((food) => (
            <div key={food.id} className="flex flex-wrap justify-between gap-2 rounded-md border p-3 text-sm">
              <strong>{food.name}</strong>
              <span>{food.calories} kcal · C {food.carbs_g}g · P {food.protein_g}g · F {food.fat_g}g</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}
