from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class GoalProfile(Base):
    __tablename__ = "goal_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    current_weight_kg: Mapped[float] = mapped_column(Numeric(5, 2))
    target_weight_kg: Mapped[float] = mapped_column(Numeric(5, 2))
    target_date: Mapped[date] = mapped_column(Date)
    daily_calorie_target: Mapped[int] = mapped_column(Integer)
    activity_level: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class MealLog(Base):
    __tablename__ = "meal_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    meal_date: Mapped[date] = mapped_column(Date, index=True)
    meal_type: Mapped[str] = mapped_column(String(20), index=True)
    meal_time: Mapped[str | None] = mapped_column(String(5))
    memo: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(500))
    crop_image_path: Mapped[str | None] = mapped_column(String(500))
    crop_x: Mapped[int | None] = mapped_column(Integer)
    crop_y: Mapped[int | None] = mapped_column(Integer)
    crop_width: Mapped[int | None] = mapped_column(Integer)
    crop_height: Mapped[int | None] = mapped_column(Integer)
    total_calories: Mapped[int] = mapped_column(Integer, default=0)
    carbs_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    protein_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    fat_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    foods = relationship("MealFoodItem", back_populates="meal", cascade="all, delete-orphan")


class MealFoodItem(Base):
    __tablename__ = "meal_food_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_log_id: Mapped[int] = mapped_column(ForeignKey("meal_logs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    calories: Mapped[int] = mapped_column(Integer)
    carbs_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    protein_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    fat_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    portion_text: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    meal = relationship("MealLog", back_populates="foods")


class FoodNutritionEstimate(Base):
    __tablename__ = "food_nutrition_estimates"
    __table_args__ = (UniqueConstraint("normalized_name", "normalized_portion", name="uq_food_nutrition_estimates_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(120), index=True)
    portion_text: Mapped[str] = mapped_column(String(100))
    normalized_portion: Mapped[str] = mapped_column(String(120), index=True)
    calories: Mapped[int] = mapped_column(Integer)
    carbs_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    protein_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    fat_g: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    source: Mapped[str] = mapped_column(String(40), default="llm")
    raw_response_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NutritionKnowledgeDoc(Base):
    __tablename__ = "nutrition_knowledge_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StrategyAdvice(Base):
    __tablename__ = "strategy_advices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal_profile_id: Mapped[int] = mapped_column(ForeignKey("goal_profiles.id", ondelete="CASCADE"), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    question: Mapped[str | None] = mapped_column(Text)
    pace_status: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    today_strategy: Mapped[str] = mapped_column(Text)
    tomorrow_strategy: Mapped[str] = mapped_column(Text)
    risk_notes_json: Mapped[list] = mapped_column(JSON, default=list)
    rag_evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    agent_trace_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
