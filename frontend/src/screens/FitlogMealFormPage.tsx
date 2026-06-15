"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import * as fitlogApi from "@/api/fitlog";
import { assetUrl } from "@/api/client";
import ImageCropPicker from "@/components/ImageCropPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { todayString } from "@/lib/date";
import type { MealFoodItem } from "@/types";

type MealType = "breakfast" | "lunch" | "dinner" | "snack";

const blankFood: MealFoodItem = { name: "", calories: 0, carbs_g: 0, protein_g: 0, fat_g: 0, portion_text: "" };
const defaultMealTimes: Record<MealType, string> = {
  breakfast: "09:00",
  lunch: "12:00",
  dinner: "18:00",
  snack: "",
};
const mealTypeOptions: Array<{ value: MealType; label: string }> = [
  { value: "breakfast", label: "아침" },
  { value: "lunch", label: "점심" },
  { value: "dinner", label: "저녁" },
  { value: "snack", label: "간식" },
];

function isMealType(value: string | null): value is MealType {
  return value === "breakfast" || value === "lunch" || value === "dinner" || value === "snack";
}

function currentTimeValue() {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

function defaultTimeFor(type: MealType) {
  return type === "snack" ? currentTimeValue() : defaultMealTimes[type];
}

function resetNutrition(food: MealFoodItem, patch: Partial<MealFoodItem>): MealFoodItem {
  return { ...food, ...patch, calories: 0, carbs_g: 0, protein_g: 0, fat_g: 0 };
}

export default function FitlogMealFormPage() {
  const router = useRouter();
  const params = useParams<{ mealId?: string }>();
  const searchParams = useSearchParams();
  const mealId = params.mealId ? Number(params.mealId) : null;
  const initialMealType = searchParams.get("meal_type");
  const initialType: MealType = isMealType(initialMealType) ? initialMealType : "lunch";
  const [mealDate, setMealDate] = useState(searchParams.get("date") ?? todayString());
  const [mealType, setMealType] = useState<MealType>(initialType);
  const [mealTime, setMealTime] = useState(defaultTimeFor(initialType));
  const [memo, setMemo] = useState("");
  const [foods, setFoods] = useState<MealFoodItem[]>([]);
  const [imageState, setImageState] = useState<{ image: File | null; cropImage: Blob | null; crop: { x: number; y: number; width: number; height: number } | null }>({ image: null, cropImage: null, crop: null });
  const [existingImages, setExistingImages] = useState<{ image?: string | null; crop?: string | null }>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mealId) return;
    fitlogApi.getMeal(mealId).then((meal) => {
      setMealDate(meal.meal_date);
      setMealType(meal.meal_type);
      setMealTime(meal.meal_time ?? defaultTimeFor(meal.meal_type));
      setMemo(meal.memo ?? "");
      setFoods(meal.foods);
      setExistingImages({ image: meal.image_path, crop: meal.crop_image_path });
    }).catch((err) => setError(err instanceof Error ? err.message : "식단 기록을 불러오지 못했습니다."));
  }, [mealId]);

  const updateFood = (index: number, patch: Partial<MealFoodItem>) => {
    setFoods((current) => current.map((food, itemIndex) => itemIndex === index ? resetNutrition(food, patch) : food));
  };

  const changeMealType = (nextType: MealType) => {
    setMealType(nextType);
    setMealTime(defaultTimeFor(nextType));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const filledFoods = foods.filter((food) => food.name.trim()).map((food) => ({ ...food, portion_text: food.portion_text?.trim() || "1인분" }));
    if (filledFoods.length === 0 && !imageState.image && !existingImages.image && !existingImages.crop) {
      setError("음식을 하나 이상 추가하거나 식단 이미지를 선택해 주세요.");
      return;
    }
    const payload = { meal_date: mealDate, meal_type: mealType, meal_time: mealTime || defaultTimeFor(mealType), memo, foods: filledFoods, image: imageState.image, cropImage: imageState.cropImage, crop: imageState.crop };
    try {
      if (mealId) {
        await fitlogApi.updateMeal(mealId, payload);
      } else {
        await fitlogApi.createMeal(payload);
      }
      router.push(`/fitlog/meals?date=${encodeURIComponent(mealDate)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "식단 기록을 저장하지 못했습니다.");
    }
  };

  return (
    <section className="grid gap-5">
      <h1 className="text-3xl font-extrabold">{mealId ? "식단 수정" : "식단 추가"}</h1>
      <form className="grid gap-5" onSubmit={submit}>
        <Card>
          <CardHeader><CardTitle>식단 정보</CardTitle></CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-4 md:grid-cols-3">
              <label className="grid gap-2 text-sm font-semibold">날짜<Input type="date" value={mealDate} onChange={(e) => setMealDate(e.target.value)} required /></label>
              <label className="grid gap-2 text-sm font-semibold">끼니
                <select className="h-10 rounded-md border bg-background px-3" value={mealType} onChange={(e) => changeMealType(e.target.value as MealType)}>
                  {mealTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-semibold">시간<Input type="time" value={mealTime} onChange={(e) => setMealTime(e.target.value)} /></label>
            </div>
            <p className="text-sm text-muted-foreground">
              아침, 점심, 저녁은 날짜별로 1개만 저장됩니다. 음식명과 분량만 입력하면 서버가 영양성분 캐시를 찾고, 없으면 LLM으로 추정해 저장합니다.
            </p>
            <label className="grid gap-2 text-sm font-semibold">
              메모
              <span className="text-xs font-normal text-muted-foreground">
                선택 입력입니다. 어디서 먹었는지, 포만감, 특이사항처럼 코치가 참고하면 좋은 내용을 적습니다.
              </span>
              <Input value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="예: 외식, 국물은 거의 남김, 포만감 높음" />
            </label>
            {existingImages.image ? <img src={assetUrl(existingImages.image)} alt="" className="max-h-56 rounded-md border object-contain" /> : null}
            {existingImages.crop ? <img src={assetUrl(existingImages.crop)} alt="" className="max-h-40 rounded-md border object-contain" /> : null}
            <ImageCropPicker onChange={(value) => setImageState({ image: value.image, cropImage: value.cropImage, crop: value.crop })} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>음식</CardTitle></CardHeader>
          <CardContent className="grid gap-3">
            <p className="text-sm text-muted-foreground">
              음식명과 분량만 입력하세요. 저장 시 서버가 영양성분을 자동으로 채우고 같은 음식/분량은 DB 캐시를 재사용합니다.
            </p>
            <div className="hidden grid-cols-[1fr_1fr_auto] gap-2 px-1 text-xs font-semibold text-muted-foreground md:grid">
              <span>음식명</span>
              <span>분량</span>
              <span>예상 영양성분</span>
            </div>
            {foods.map((food, index) => (
              <div key={index} className="grid gap-2 rounded-md border p-3 md:grid-cols-[1fr_1fr_auto]">
                <label className="grid gap-1 text-xs font-semibold md:block">
                  <span className="md:hidden">음식명</span>
                  <Input placeholder="김치찌개" value={food.name} onChange={(e) => updateFood(index, { name: e.target.value })} required />
                </label>
                <label className="grid gap-1 text-xs font-semibold md:block">
                  <span className="md:hidden">분량</span>
                  <Input placeholder="1인분, 200g, 한 그릇" value={food.portion_text ?? ""} onChange={(e) => updateFood(index, { portion_text: e.target.value })} />
                </label>
                <div className="self-center text-xs text-muted-foreground">
                  {food.calories > 0 ? `${food.calories} kcal · 탄 ${food.carbs_g}g · 단 ${food.protein_g}g · 지 ${food.fat_g}g` : "저장 시 자동 추정"}
                </div>
              </div>
            ))}
            {foods.length === 0 ? (
              <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                아직 추가된 음식이 없습니다. 아래 버튼으로 음식 입력 행을 추가하거나 이미지만 선택해서 테스트 분석을 사용할 수 있습니다.
              </p>
            ) : null}
            <Button type="button" variant="outline" className="w-fit" onClick={() => setFoods((current) => [...current, { ...blankFood }])}>음식 추가</Button>
          </CardContent>
        </Card>
        {error ? <p className="font-semibold text-destructive">{error}</p> : null}
        <Button type="submit" className="w-fit">저장</Button>
      </form>
    </section>
  );
}
