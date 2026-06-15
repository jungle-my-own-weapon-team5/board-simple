"""add meal time

Revision ID: 0004_meal_time
Revises: 0003_fitlog_schema
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_meal_time"
down_revision: Union[str, None] = "0003_fitlog_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meal_logs", sa.Column("meal_time", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("meal_logs", "meal_time")
