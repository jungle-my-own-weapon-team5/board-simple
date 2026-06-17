"""use langchain openai embeddings for nutrition knowledge

Revision ID: 0007_langchain_openai_embeddings
Revises: 0006_food_nutrition_estimates
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007_langchain_openai_embeddings"
down_revision: Union[str, None] = "0006_food_nutrition_estimates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE nutrition_knowledge_docs DROP COLUMN IF EXISTS embedding")
        op.execute("ALTER TABLE nutrition_knowledge_docs ADD COLUMN embedding vector(1536)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE nutrition_knowledge_docs DROP COLUMN IF EXISTS embedding")
        op.execute("ALTER TABLE nutrition_knowledge_docs ADD COLUMN embedding vector(64)")
