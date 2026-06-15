import { apiRequest } from "./client";
import type { DailyReport, GoalProfile, ImageSearchTestResponse, MealFoodItem, MealLog, StrategyAdvice, StrategyResponse } from "../types";

export function getGoal() {
  return apiRequest<GoalProfile>("/api/fitlog/goals/me");
}

export function saveGoal(payload: {
  current_weight_kg: number;
  target_weight_kg: number;
  target_date: string;
  daily_calorie_target: number;
  activity_level: "low" | "moderate" | "high";
}) {
  return apiRequest<GoalProfile>("/api/fitlog/goals", { method: "POST", json: payload });
}

export type MealPayload = {
  meal_date: string;
  meal_type: "breakfast" | "lunch" | "dinner" | "snack";
  meal_time?: string | null;
  memo?: string;
  foods: MealFoodItem[];
  image?: Blob | null;
  cropImage?: Blob | null;
  crop?: { x: number; y: number; width: number; height: number } | null;
};

function mealForm(payload: MealPayload) {
  const form = new FormData();
  form.set("meal_date", payload.meal_date);
  form.set("meal_type", payload.meal_type);
  if (payload.meal_time) {
    form.set("meal_time", payload.meal_time);
  }
  form.set("memo", payload.memo ?? "");
  form.set("foods_json", JSON.stringify(payload.foods));
  if (payload.image) {
    form.set("image", payload.image, "meal.jpg");
  }
  if (payload.cropImage) {
    form.set("crop_image", payload.cropImage, "meal-crop.jpg");
  }
  if (payload.crop) {
    form.set("crop_x", String(Math.round(payload.crop.x)));
    form.set("crop_y", String(Math.round(payload.crop.y)));
    form.set("crop_width", String(Math.round(payload.crop.width)));
    form.set("crop_height", String(Math.round(payload.crop.height)));
  }
  return form;
}

export function createMeal(payload: MealPayload) {
  return apiRequest<MealLog>("/api/fitlog/meals", { method: "POST", body: mealForm(payload) });
}

export function updateMeal(mealId: number, payload: MealPayload) {
  return apiRequest<MealLog>(`/api/fitlog/meals/${mealId}`, { method: "PUT", body: mealForm(payload) });
}

export function listMeals(date: string) {
  return apiRequest<{ items: MealLog[] }>(`/api/fitlog/meals?date=${encodeURIComponent(date)}`);
}

export function getMeal(mealId: number) {
  return apiRequest<MealLog>(`/api/fitlog/meals/${mealId}`);
}

export function deleteMeal(mealId: number) {
  return apiRequest<void>(`/api/fitlog/meals/${mealId}`, { method: "DELETE" });
}

export function getDailyReport(date: string) {
  return apiRequest<DailyReport>(`/api/fitlog/reports/daily?date=${encodeURIComponent(date)}`);
}

export function createStrategy(payload: { date: string; question?: string }) {
  return apiRequest<StrategyResponse>("/api/fitlog/strategy", { method: "POST", json: payload });
}

export function listStrategies(date?: string) {
  const suffix = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiRequest<{ items: StrategyAdvice[] }>(`/api/fitlog/strategy${suffix}`);
}

export function imageSearchTest(image: Blob) {
  const form = new FormData();
  form.set("image", image, "query.jpg");
  return apiRequest<ImageSearchTestResponse>("/api/fitlog/image-search-test", { method: "POST", body: form });
}
