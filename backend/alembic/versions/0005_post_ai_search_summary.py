"""add post ai search summary

Revision ID: 0005_post_ai_search_summary
Revises: 0004_ai_rag_tables
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_post_ai_search_summary"
down_revision: Union[str, None] = "0004_ai_rag_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("ai_search_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "ai_search_summary")
