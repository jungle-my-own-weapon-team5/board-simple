"""add post thumbnail url

Revision ID: 0006_post_thumbnail_url
Revises: 0005_post_ai_search_summary
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_post_thumbnail_url"
down_revision: Union[str, None] = "0005_post_ai_search_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("thumbnail_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "thumbnail_url")
