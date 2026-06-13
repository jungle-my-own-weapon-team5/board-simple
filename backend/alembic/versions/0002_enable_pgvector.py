"""enable pgvector extension

Revision ID: 0002_enable_pgvector
Revises: 0001_initial_schema
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_enable_pgvector"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")
