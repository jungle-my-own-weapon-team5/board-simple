"""add post source metadata

Revision ID: 0004_post_sources
Revises: 0003_post_rag_chunks
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_post_sources"
down_revision: Union[str, None] = "0003_post_rag_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("source_type", sa.String(length=50), nullable=True))
    op.add_column("posts", sa.Column("source_id", sa.String(length=100), nullable=True))
    op.add_column("posts", sa.Column("source_url", sa.String(length=2048), nullable=True))
    op.add_column("posts", sa.Column("source_title", sa.String(length=500), nullable=True))
    op.add_column("posts", sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_posts_source_type_source_id",
        "posts",
        ["source_type", "source_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_posts_source_type_source_id", table_name="posts")
    op.drop_column("posts", "source_fetched_at")
    op.drop_column("posts", "source_title")
    op.drop_column("posts", "source_url")
    op.drop_column("posts", "source_id")
    op.drop_column("posts", "source_type")
