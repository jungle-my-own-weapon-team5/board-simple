"""add pgvector index for rag chunks

Revision ID: 0009_rag_chunks_pgvector_index
Revises: 0008_discussion_topics
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009_rag_chunks_pgvector_index"
down_revision: Union[str, None] = "0008_discussion_topics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_cosine "
            "ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding_cosine")
