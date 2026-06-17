from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ActivityLevel = Literal["low", "moderate", "high"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]
PaceStatus = Literal["on_track", "slightly_over", "over", "insufficient_data", "goal_too_aggressive"]


class GoalProfileBase(BaseModel):
    current_weight_kg: float = Field(gt=0)
    target_weight_kg: float = Field(gt=0)
    target_date: date
    daily_calorie_target: int = Field(gt=0)
    activity_level: ActivityLevel


class GoalProfileCreate(GoalProfileBase):
    pass


class GoalProfileRead(GoalProfileBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MealFoodItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    calories: int = Field(default=0, ge=0)
    carbs_g: float = Field(default=0, ge=0)
    protein_g: float = Field(default=0, ge=0)
    fat_g: float = Field(default=0, ge=0)
    portion_text: str | None = Field(default=None, max_length=100)
    image_path: str | None = Field(default=None, max_length=500)
    image_data_url: str | None = None


class MealFoodItemRead(MealFoodItemInput):
    id: int

    model_config = {"from_attributes": True}


class MealLogRead(BaseModel):
    id: int
    meal_date: date
    meal_type: MealType
    meal_time: str | None
    memo: str | None
    image_path: str | None
    crop_image_path: str | None
    crop_x: int | None
    crop_y: int | None
    crop_width: int | None
    crop_height: int | None
    total_calories: int
    carbs_g: float
    protein_g: float
    fat_g: float
    foods: list[MealFoodItemRead]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MealLogList(BaseModel):
    items: list[MealLogRead]


class MealSummary(BaseModel):
    id: int
    meal_type: str
    total_calories: int
    carbs_g: float
    protein_g: float
    fat_g: float


class DailyReport(BaseModel):
    date: date
    daily_calorie_target: int | None
    total_calories: int
    remaining_calories: int | None
    carbs_g: float
    protein_g: float
    fat_g: float
    meal_count: int
    status: str
    warnings: list[str]
    meals: list[MealSummary]


class StrategyRequest(BaseModel):
    date: date
    question: str | None = None


class RagEvidence(BaseModel):
    title: str
    snippet: str
    source_url: str | None = None


class AgentStep(BaseModel):
    tool: str
    status: str
    summary: str


class StrategyResponse(BaseModel):
    date: date
    pace_status: PaceStatus
    summary: str
    today_strategy: str
    tomorrow_strategy: str
    risk_notes: list[str]
    rag_evidence: list[RagEvidence]
    agent_steps: list[AgentStep] = Field(default_factory=list)


class StrategyAdviceRead(StrategyResponse):
    id: int
    question: str | None
    created_at: datetime


class StrategyAdviceList(BaseModel):
    items: list[StrategyAdviceRead]


class ImageSearchCandidate(BaseModel):
    food_name: str
    similarity: float
    estimated_calories: int
    carbs_g: float
    protein_g: float
    fat_g: float
    notes: list[str]


class ImageSearchTestResponse(BaseModel):
    query_handled: bool
    mode: str
    top_k: list[ImageSearchCandidate]
