"""rag chunks pgvector index

Revision ID: 0009_rag_chunks_pgvector_index
Revises: 0008_discussion_topics
Create Date: 2026-06-18
"""

from typing import Sequence

from alembic import op

revision: str = "0009_rag_chunks_pgvector_index"
down_revision: str | None = "0008_discussion_topics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw ON rag_chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding_hnsw")
