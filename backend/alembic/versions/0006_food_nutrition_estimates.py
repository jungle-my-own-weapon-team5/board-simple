"""add food nutrition estimates

Revision ID: 0006_food_nutrition_estimates
Revises: 0005_knowledge_vector
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_food_nutrition_estimates"
down_revision: Union[str, None] = "0005_knowledge_vector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "food_nutrition_estimates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("normalized_name", sa.String(120), nullable=False),
        sa.Column("portion_text", sa.String(100), nullable=False),
        sa.Column("normalized_portion", sa.String(120), nullable=False),
        sa.Column("calories", sa.Integer(), nullable=False),
        sa.Column("carbs_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("protein_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("fat_g", sa.Numeric(8, 2), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", "normalized_portion", name="uq_food_nutrition_estimates_key"),
    )
    op.create_index("ix_food_nutrition_estimates_normalized_name", "food_nutrition_estimates", ["normalized_name"])
    op.create_index("ix_food_nutrition_estimates_normalized_portion", "food_nutrition_estimates", ["normalized_portion"])


def downgrade() -> None:
    op.drop_index("ix_food_nutrition_estimates_normalized_portion", table_name="food_nutrition_estimates")
    op.drop_index("ix_food_nutrition_estimates_normalized_name", table_name="food_nutrition_estimates")
    op.drop_table("food_nutrition_estimates")
