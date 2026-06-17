"""add food item image path

Revision ID: 0009_food_item_image_path
Revises: 0008_strategy_agent_trace
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_food_item_image_path"
down_revision: Union[str, None] = "0008_strategy_agent_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meal_food_items", sa.Column("image_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("meal_food_items", "image_path")
