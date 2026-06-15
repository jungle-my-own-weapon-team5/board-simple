export type User = {
  id: number;
  email: string;
  nickname: string;
  created_at: string;
};

export type Tag = {
  id: number;
  name: string;
};

export type Post = {
  id: number;
  title: string;
  content: string;
  author: User;
  tags: Tag[];
  created_at: string;
  updated_at: string;
};

export type PostListItem = Omit<Post, "content">;

export type PostPage = {
  items: PostListItem[];
  total: number;
  page: number;
  size: number;
};

export type Comment = {
  id: number;
  post_id: number;
  content: string;
  author: User;
  created_at: string;
  updated_at: string;
};

export type CommentPage = {
  items: Comment[];
  total: number;
  offset: number;
  limit: number;
};

export type GoalProfile = {
  id: number;
  current_weight_kg: number;
  target_weight_kg: number;
  target_date: string;
  daily_calorie_target: number;
  activity_level: "low" | "moderate" | "high";
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type MealFoodItem = {
  id?: number;
  name: string;
  calories: number;
  carbs_g: number;
  protein_g: number;
  fat_g: number;
  portion_text?: string | null;
};

export type MealLog = {
  id: number;
  meal_date: string;
  meal_type: "breakfast" | "lunch" | "dinner" | "snack";
  meal_time?: string | null;
  memo?: string | null;
  image_path?: string | null;
  crop_image_path?: string | null;
  crop_x?: number | null;
  crop_y?: number | null;
  crop_width?: number | null;
  crop_height?: number | null;
  total_calories: number;
  carbs_g: number;
  protein_g: number;
  fat_g: number;
  foods: MealFoodItem[];
  created_at: string;
  updated_at: string;
};

export type DailyReport = {
  date: string;
  daily_calorie_target: number | null;
  total_calories: number;
  remaining_calories: number | null;
  carbs_g: number;
  protein_g: number;
  fat_g: number;
  meal_count: number;
  status: string;
  warnings: string[];
  meals: Array<{ id: number; meal_type: string; total_calories: number; carbs_g: number; protein_g: number; fat_g: number }>;
};

export type StrategyResponse = {
  date: string;
  pace_status: string;
  summary: string;
  today_strategy: string;
  tomorrow_strategy: string;
  risk_notes: string[];
  rag_evidence: Array<{ title: string; snippet: string; source_url?: string | null }>;
};

export type StrategyAdvice = StrategyResponse & {
  id: number;
  question?: string | null;
  created_at: string;
};

export type ImageSearchTestResponse = {
  query_handled: boolean;
  mode: string;
  top_k: Array<{
    food_name: string;
    similarity: number;
    estimated_calories: number;
    carbs_g: number;
    protein_g: number;
    fat_g: number;
    notes: string[];
  }>;
};
