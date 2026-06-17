"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Trash2 } from "lucide-react";
import * as fitlogApi from "@/api/fitlog";
import { assetUrl } from "@/api/client";
import ImageCropPicker from "@/components/ImageCropPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { todayString } from "@/lib/date";
import type { ImageRagCandidate, ImageRagSearchResponse, MealFoodItem } from "@/types";

type MealType = "breakfast" | "lunch" | "dinner" | "snack";
type FormFoodItem = MealFoodItem & { imagePreviewUrl?: string | null };

const blankFood: FormFoodItem = { name: "", calories: 0, carbs_g: 0, protein_g: 0, fat_g: 0, portion_text: "" };
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

function resetNutrition(food: FormFoodItem, patch: Partial<MealFoodItem>): FormFoodItem {
  return { ...food, ...patch, calories: 0, carbs_g: 0, protein_g: 0, fat_g: 0 };
}

function imageCandidateToFood(candidate: ImageRagCandidate, imagePreviewUrl?: string | null): FormFoodItem {
  return {
    name: candidate.food_name,
    calories: candidate.estimated_calories,
    carbs_g: candidate.carbs_g,
    protein_g: candidate.protein_g,
    fat_g: candidate.fat_g,
    imagePreviewUrl,
    image_data_url: imagePreviewUrl?.startsWith("data:") ? imagePreviewUrl : undefined,
    portion_text: "1인분",
  };
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read image preview"));
    reader.readAsDataURL(blob);
  });
}

function stripFoodPreview(food: FormFoodItem): MealFoodItem {
  const { imagePreviewUrl: _imagePreviewUrl, ...foodPayload } = food;
  return foodPayload;
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
  const [foods, setFoods] = useState<FormFoodItem[]>([]);
  const [imageState, setImageState] = useState<{
    image: File | null;
    cropImage: Blob | null;
    crop: { x: number; y: number; width: number; height: number } | null;
    previewUrl: string | null;
    cropPreviewUrl: string | null;
  }>({ image: null, cropImage: null, crop: null, previewUrl: null, cropPreviewUrl: null });
  const [existingImages, setExistingImages] = useState<{ image?: string | null; crop?: string | null }>({});
  const [imageAnalysis, setImageAnalysis] = useState<ImageRagSearchResponse | null>(null);
  const [imagePickerVersion, setImagePickerVersion] = useState(0);
  const [isImageCandidateApplied, setIsImageCandidateApplied] = useState(false);
  const [isAnalyzingImage, setIsAnalyzingImage] = useState(false);
  const [imageAnalysisError, setImageAnalysisError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mealId) return;
    fitlogApi.getMeal(mealId)
      .then((meal) => {
        setMealDate(meal.meal_date);
        setMealType(meal.meal_type);
        setMealTime(meal.meal_time ?? defaultTimeFor(meal.meal_type));
        setMemo(meal.memo ?? "");
        setFoods(meal.foods.map((food) => ({ ...food, imagePreviewUrl: food.image_path ? assetUrl(food.image_path) : null })));
        setExistingImages({ image: meal.image_path, crop: meal.crop_image_path });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "식단 기록을 불러오지 못했습니다."));
  }, [mealId]);

  const updateFood = (index: number, patch: Partial<MealFoodItem>) => {
    setFoods((current) => current.map((food, itemIndex) => (itemIndex === index ? resetNutrition(food, patch) : food)));
  };

  const applyImageCandidate = async (candidate: ImageRagCandidate) => {
    const previewSource = imageState.cropImage ?? imageState.image;
    const stablePreviewUrl = previewSource ? await blobToDataUrl(previewSource) : null;
    const nextFood = imageCandidateToFood(candidate, stablePreviewUrl ?? imageState.cropPreviewUrl ?? imageState.previewUrl);
    setFoods((current) => {
      const duplicateIndex = current.findIndex((food) => food.name.trim().toLowerCase() === nextFood.name.trim().toLowerCase());
      if (duplicateIndex >= 0) {
        return current.map((food, index) => (index === duplicateIndex ? nextFood : food));
      }
      const emptyIndex = current.findIndex((food) => !food.name.trim());
      if (emptyIndex >= 0) {
        return current.map((food, index) => (index === emptyIndex ? nextFood : food));
      }
      return [...current, nextFood];
    });
    setImageAnalysis(null);
    setImageAnalysisError(null);
    setIsImageCandidateApplied(true);
  };

  const removeFood = (index: number) => {
    setFoods((current) => current.filter((_, itemIndex) => itemIndex !== index));
  };

  const analyzeImage = async () => {
    if (isImageCandidateApplied) {
      setImageAnalysisError("이미 반영된 이미지입니다. 다시 분석하려면 다른 이미지를 선택하거나 선택 취소 후 다시 선택해 주세요.");
      return;
    }
    const selectedCrop = imageState.crop && imageState.crop.width >= 8 && imageState.crop.height >= 8 ? imageState.crop : null;
    if (selectedCrop && !imageState.cropImage) {
      setImageAnalysisError("선택 영역 이미지를 준비 중입니다. 잠시 후 다시 분석해 주세요.");
      return;
    }
    const targetImage = selectedCrop ? imageState.cropImage : imageState.image;
    if (!targetImage) {
      setImageAnalysisError("분석할 이미지를 먼저 선택해 주세요.");
      return;
    }
    setIsAnalyzingImage(true);
    setImageAnalysisError(null);
    setImageAnalysis(null);
    try {
      const result = await fitlogApi.searchImageRag(targetImage);
      setImageAnalysis(result);
      if (result.action === "auto_accept_label" && result.top_k[0]) {
        await applyImageCandidate(result.top_k[0]);
      }
    } catch (err) {
      setImageAnalysisError(err instanceof Error ? err.message : "이미지 분석에 실패했습니다.");
    } finally {
      setIsAnalyzingImage(false);
    }
  };

  const changeMealType = (nextType: MealType) => {
    setMealType(nextType);
    setMealTime(defaultTimeFor(nextType));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const filledFoods = foods
      .filter((food) => food.name.trim())
      .map(stripFoodPreview)
      .map((food) => ({ ...food, portion_text: food.portion_text?.trim() || "1인분" }));
    if (filledFoods.length === 0 && !imageState.image && !existingImages.image && !existingImages.crop) {
      setError("음식을 하나 이상 추가하거나 식단 이미지를 선택해 주세요.");
      return;
    }
    const payload = {
      meal_date: mealDate,
      meal_type: mealType,
      meal_time: mealTime || defaultTimeFor(mealType),
      memo,
      foods: filledFoods,
      image: imageState.image,
      cropImage: imageState.cropImage,
      crop: imageState.crop,
    };
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

  const hasSelectedCrop = Boolean(imageState.crop && imageState.crop.width >= 8 && imageState.crop.height >= 8);

  return (
    <section className="grid gap-5">
      <h1 className="text-3xl font-extrabold">{mealId ? "식단 수정" : "식단 추가"}</h1>
      <form className="grid gap-5" onSubmit={submit}>
        <Card>
          <CardHeader><CardTitle>식단 정보</CardTitle></CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-4 md:grid-cols-3">
              <label className="grid gap-2 text-sm font-semibold">날짜<Input type="date" value={mealDate} onChange={(e) => setMealDate(e.target.value)} required /></label>
              <label className="grid gap-2 text-sm font-semibold">시간대
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
              <Input value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="예: 외식, 국물은 거의 안 먹음, 포만감 높음" />
            </label>
            {existingImages.image ? <img src={assetUrl(existingImages.image)} alt="" className="max-h-56 rounded-md border object-contain" /> : null}
            {existingImages.crop ? <img src={assetUrl(existingImages.crop)} alt="" className="max-h-40 rounded-md border object-contain" /> : null}
            <ImageCropPicker key={imagePickerVersion} onChange={(value) => {
              setImageState({ image: value.image, cropImage: value.cropImage, crop: value.crop, previewUrl: value.previewUrl, cropPreviewUrl: value.cropPreviewUrl });
              setImageAnalysis(null);
              setImageAnalysisError(null);
              setIsImageCandidateApplied(false);
            }} />
            <div className="grid gap-3 rounded-md border p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">이미지 음식 분석</p>
                  <p className="text-xs text-muted-foreground">선택 영역이 있으면 잘라낸 이미지를 우선 분석합니다.</p>
                </div>
                <Button type="button" variant="outline" onClick={analyzeImage} disabled={isAnalyzingImage || isImageCandidateApplied || !imageState.image || (hasSelectedCrop && !imageState.cropImage)}>
                  {isAnalyzingImage ? "분석 중..." : "음식 분석"}
                </Button>
              </div>
              {imageAnalysisError ? <p className="text-sm font-semibold text-destructive">{imageAnalysisError}</p> : null}
              {imageAnalysis ? (
                <div className="grid gap-2">
                  <p className="text-xs text-muted-foreground">
                    {imageAnalysis.action === "auto_accept_label" ? "신뢰도가 높아 첫 번째 후보를 Foods에 반영했습니다." : "후보를 확인하고 하나를 선택하면 Foods에 반영됩니다."}
                  </p>
                  <div className="grid gap-2 md:grid-cols-3">
                    {imageAnalysis.top_k.map((candidate) => (
                      <button
                        key={`${candidate.food_name}-${candidate.confidence}`}
                        type="button"
                        className="grid gap-1 rounded-md border p-3 text-left text-sm hover:bg-accent"
                        onClick={() => { void applyImageCandidate(candidate); }}
                      >
                        <span className="font-semibold">{candidate.food_name}</span>
                        <span className="text-xs text-muted-foreground">신뢰도 {(candidate.confidence * 100).toFixed(1)}%</span>
                        <span className="text-xs text-muted-foreground">
                          {candidate.estimated_calories} kcal · 탄 {candidate.carbs_g}g · 단 {candidate.protein_g}g · 지 {candidate.fat_g}g
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>음식</CardTitle></CardHeader>
          <CardContent className="grid gap-3">
            <p className="text-sm text-muted-foreground">
              음식명과 분량만 입력하세요. 저장할 때 서버가 영양성분을 자동으로 채우고 같은 음식/분량은 DB 캐시를 재사용합니다.
            </p>
            <div className="hidden grid-cols-[1fr_1fr_auto_auto] gap-2 px-1 text-xs font-semibold text-muted-foreground md:grid">
              <span>음식명</span>
              <span>분량</span>
              <span>예상 영양성분</span>
              <span>삭제</span>
            </div>
            {foods.map((food, index) => (
              <div key={index} className="grid grid-cols-[72px_minmax(0,1fr)] gap-2 rounded-md border p-3 md:grid-cols-[80px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
                <div className="row-span-3 h-20 w-20 self-start overflow-hidden rounded-md border bg-muted/20 md:row-span-2">
                  {food.imagePreviewUrl ? (
                    <img src={food.imagePreviewUrl} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <div className="h-full w-full" />
                  )}
                </div>
                <label className="grid gap-1 text-xs font-semibold md:block">
                  <span className="md:hidden">음식명</span>
                  <Input placeholder="김치찌개" value={food.name} onChange={(e) => updateFood(index, { name: e.target.value })} required />
                </label>
                <label className="grid gap-1 text-xs font-semibold md:block">
                  <span className="md:hidden">분량</span>
                  <Input placeholder="1인분, 200g, 한 그릇" value={food.portion_text ?? ""} onChange={(e) => updateFood(index, { portion_text: e.target.value })} />
                </label>
                <div className="col-start-2 self-center text-xs text-muted-foreground md:col-span-2">
                  {food.calories > 0 ? `${food.calories} kcal · 탄 ${food.carbs_g}g · 단 ${food.protein_g}g · 지 ${food.fat_g}g` : "저장 시 자동 추정"}
                </div>
                <Button type="button" variant="outline" size="sm" className="col-start-2 w-fit self-center md:col-start-5 md:row-start-2" onClick={() => removeFood(index)} aria-label={`${food.name || "음식"} 삭제`}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            {foods.length === 0 ? (
              <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                아직 추가한 음식이 없습니다. 아래 버튼으로 음식 입력 행을 추가하거나 이미지를 선택해서 테스트 분석을 사용할 수 있습니다.
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
