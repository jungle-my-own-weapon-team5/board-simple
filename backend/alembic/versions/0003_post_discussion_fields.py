"""add post discussion fields

Revision ID: 0003_post_discussion_fields
Revises: 0002_enable_pgvector
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_post_discussion_fields"
down_revision: Union[str, None] = "0002_enable_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("post_type", sa.String(length=20), server_default="토론", nullable=False),
    )
    op.add_column(
        "posts",
        sa.Column("category", sa.String(length=50), server_default="왕과 권력", nullable=False),
    )
    op.add_column(
        "posts",
        sa.Column("view_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "posts",
        sa.Column("comment_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("posts", "comment_count")
    op.drop_column("posts", "view_count")
    op.drop_column("posts", "category")
    op.drop_column("posts", "post_type")
