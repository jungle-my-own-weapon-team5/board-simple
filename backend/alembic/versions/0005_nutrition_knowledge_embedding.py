"""add nutrition knowledge embedding

Revision ID: 0005_knowledge_vector
Revises: 0004_meal_time
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_knowledge_vector"
down_revision: Union[str, None] = "0004_meal_time"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE nutrition_knowledge_docs ADD COLUMN embedding vector(64)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE nutrition_knowledge_docs DROP COLUMN IF EXISTS embedding")
