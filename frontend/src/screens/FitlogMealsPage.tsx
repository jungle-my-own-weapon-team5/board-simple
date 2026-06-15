"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import * as fitlogApi from "@/api/fitlog";
import { assetUrl } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { todayString } from "@/lib/date";
import type { MealLog } from "@/types";

type MainMealType = "breakfast" | "lunch" | "dinner";
type AddMealType = MainMealType | "snack";

const mainSlots: Array<{ type: MainMealType; label: string }> = [
  { type: "breakfast", label: "아침" },
  { type: "lunch", label: "점심" },
  { type: "dinner", label: "저녁" },
];

const addActions: Array<{ type: AddMealType; label: string }> = [
  { type: "breakfast", label: "아침 등록" },
  { type: "lunch", label: "점심 등록" },
  { type: "dinner", label: "저녁 등록" },
  { type: "snack", label: "간식 추가" },
];

function mealTitle(meal: MealLog) {
  return meal.foods.map((food) => food.name).join(", ") || "음식명 없음";
}

function mealTimeText(meal: MealLog) {
  return meal.meal_time ? `${meal.meal_time} · ` : "";
}

function MealCard({ meal }: { meal: MealLog }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="text-lg">{mealTitle(meal)}</CardTitle>
          <p className="text-sm text-muted-foreground">{mealTimeText(meal)}{meal.total_calories} kcal</p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={`/fitlog/meals/${meal.id}`}>보기</Link>
        </Button>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-[120px_1fr]">
        {meal.crop_image_path || meal.image_path ? (
          <img
            src={assetUrl(meal.crop_image_path ?? meal.image_path)}
            alt=""
            className="h-24 w-24 rounded-md border object-cover"
          />
        ) : (
          <div className="grid h-24 w-24 place-items-center rounded-md border text-xs text-muted-foreground">이미지 없음</div>
        )}
        <div className="grid gap-1 text-sm">
          <p>탄수화물 {meal.carbs_g}g · 단백질 {meal.protein_g}g · 지방 {meal.fat_g}g</p>
          {meal.memo ? <p className="text-muted-foreground">{meal.memo}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

export default function FitlogMealsPage() {
  const params = useSearchParams();
  const [date, setDate] = useState(params.get("date") ?? todayString());
  const [items, setItems] = useState<MealLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isAddMenuOpen, setIsAddMenuOpen] = useState(false);
  const addMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setError(null);
    fitlogApi
      .listMeals(date)
      .then((data) => setItems(data.items))
      .catch((err) => setError(err instanceof Error ? err.message : "식단 기록을 불러오지 못했습니다."));
  }, [date]);

  useEffect(() => {
    if (!isAddMenuOpen) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!addMenuRef.current?.contains(event.target as Node)) {
        setIsAddMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsAddMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isAddMenuOpen]);

  const grouped = useMemo(() => {
    const main = {
      breakfast: items.find((meal) => meal.meal_type === "breakfast"),
      lunch: items.find((meal) => meal.meal_type === "lunch"),
      dinner: items.find((meal) => meal.meal_type === "dinner"),
    };
    const snacks = items
      .filter((meal) => meal.meal_type === "snack")
      .sort((a, b) => (a.meal_time ?? "99:99").localeCompare(b.meal_time ?? "99:99") || a.id - b.id);
    return { main, snacks };
  }, [items]);

  const newMealHref = (mealType: string) => `/fitlog/meals/new?date=${encodeURIComponent(date)}&meal_type=${mealType}`;

  return (
    <section className="grid gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-extrabold">식단 기록</h1>
          <p className="text-sm text-muted-foreground">아침, 점심, 저녁은 하루 한 칸으로 관리하고 간식은 시간순으로 확인합니다.</p>
        </div>
        <div ref={addMenuRef} className="relative mr-0 sm:mr-16 lg:mr-28">
          <Button
            type="button"
            aria-expanded={isAddMenuOpen}
            aria-controls="fitlog-add-menu"
            onClick={() => setIsAddMenuOpen((current) => !current)}
          >
            식단 추가
          </Button>
          {isAddMenuOpen ? (
            <div
              id="fitlog-add-menu"
              className="absolute right-0 z-10 mt-2 grid min-w-40 gap-1 rounded-md border bg-background p-2 shadow-lg"
            >
              {addActions.map((action) => (
                <Button key={action.type} asChild variant="ghost" className="justify-start">
                  <Link href={newMealHref(action.type)} onClick={() => setIsAddMenuOpen(false)}>
                    {action.label}
                  </Link>
                </Button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <label className="grid max-w-64 gap-2 text-sm font-semibold">
        날짜
        <Input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
      </label>
      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      <div className="grid gap-4">
        {mainSlots.map((slot) => {
          const meal = grouped.main[slot.type];
          return (
            <section key={slot.type} className="grid gap-2">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-xl font-bold">{slot.label}</h2>
                <Button asChild variant={meal ? "outline" : "default"} size="sm">
                  <Link href={newMealHref(slot.type)}>{meal ? "다시 등록" : "등록"}</Link>
                </Button>
              </div>
              {meal ? (
                <MealCard meal={meal} />
              ) : (
                <Card>
                  <CardContent className="p-5 text-sm text-muted-foreground">
                    {slot.label} 기록이 없습니다.
                  </CardContent>
                </Card>
              )}
            </section>
          );
        })}
        <section className="grid gap-2">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xl font-bold">간식</h2>
            <Button asChild variant="outline" size="sm">
              <Link href={newMealHref("snack")}>추가</Link>
            </Button>
          </div>
          {grouped.snacks.length === 0 ? (
            <Card>
              <CardContent className="p-5 text-sm text-muted-foreground">
                간식 기록이 없습니다.
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3">
              {grouped.snacks.map((meal) => <MealCard key={meal.id} meal={meal} />)}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
