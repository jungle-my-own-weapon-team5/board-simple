"""fitlog schema

Revision ID: 0003_fitlog_schema
Revises: 0002_enable_pgvector
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_fitlog_schema"
down_revision: Union[str, None] = "0002_enable_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "goal_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("current_weight_kg", sa.Numeric(5, 2), nullable=False),
        sa.Column("target_weight_kg", sa.Numeric(5, 2), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("daily_calorie_target", sa.Integer(), nullable=False),
        sa.Column("activity_level", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goal_profiles_user_id", "goal_profiles", ["user_id"])
    op.create_index("ix_goal_profiles_is_active", "goal_profiles", ["is_active"])

    op.create_table(
        "meal_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("meal_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(20), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("crop_image_path", sa.String(500), nullable=True),
        sa.Column("crop_x", sa.Integer(), nullable=True),
        sa.Column("crop_y", sa.Integer(), nullable=True),
        sa.Column("crop_width", sa.Integer(), nullable=True),
        sa.Column("crop_height", sa.Integer(), nullable=True),
        sa.Column("total_calories", sa.Integer(), nullable=False),
        sa.Column("carbs_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("protein_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("fat_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_logs_user_id", "meal_logs", ["user_id"])
    op.create_index("ix_meal_logs_meal_date", "meal_logs", ["meal_date"])
    op.create_index("ix_meal_logs_meal_type", "meal_logs", ["meal_type"])
    op.create_index("ix_meal_logs_user_date", "meal_logs", ["user_id", "meal_date"])

    op.create_table(
        "meal_food_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meal_log_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("calories", sa.Integer(), nullable=False),
        sa.Column("carbs_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("protein_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("fat_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("portion_text", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_food_items_meal_log_id", "meal_food_items", ["meal_log_id"])

    op.create_table(
        "nutrition_knowledge_docs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nutrition_knowledge_docs_category", "nutrition_knowledge_docs", ["category"])

    op.create_table(
        "strategy_advices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_profile_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("pace_status", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("today_strategy", sa.Text(), nullable=False),
        sa.Column("tomorrow_strategy", sa.Text(), nullable=False),
        sa.Column("risk_notes_json", sa.JSON(), nullable=False),
        sa.Column("rag_evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["goal_profile_id"], ["goal_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_advices_user_id", "strategy_advices", ["user_id"])
    op.create_index("ix_strategy_advices_goal_profile_id", "strategy_advices", ["goal_profile_id"])
    op.create_index("ix_strategy_advices_target_date", "strategy_advices", ["target_date"])


def downgrade() -> None:
    op.drop_index("ix_strategy_advices_target_date", table_name="strategy_advices")
    op.drop_index("ix_strategy_advices_goal_profile_id", table_name="strategy_advices")
    op.drop_index("ix_strategy_advices_user_id", table_name="strategy_advices")
    op.drop_table("strategy_advices")
    op.drop_index("ix_nutrition_knowledge_docs_category", table_name="nutrition_knowledge_docs")
    op.drop_table("nutrition_knowledge_docs")
    op.drop_index("ix_meal_food_items_meal_log_id", table_name="meal_food_items")
    op.drop_table("meal_food_items")
    op.drop_index("ix_meal_logs_user_date", table_name="meal_logs")
    op.drop_index("ix_meal_logs_meal_type", table_name="meal_logs")
    op.drop_index("ix_meal_logs_meal_date", table_name="meal_logs")
    op.drop_index("ix_meal_logs_user_id", table_name="meal_logs")
    op.drop_table("meal_logs")
    op.drop_index("ix_goal_profiles_is_active", table_name="goal_profiles")
    op.drop_index("ix_goal_profiles_user_id", table_name="goal_profiles")
    op.drop_table("goal_profiles")
