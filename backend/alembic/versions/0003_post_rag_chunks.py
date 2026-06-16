"""add post rag chunk mappings

Revision ID: 0003_post_rag_chunks
Revises: 0002_enable_pgvector
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_post_rag_chunks"
down_revision: Union[str, None] = "0002_enable_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post_rag_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_post_rag_chunks_id"), "post_rag_chunks", ["id"], unique=False)
    op.create_index(op.f("ix_post_rag_chunks_post_id"), "post_rag_chunks", ["post_id"], unique=False)
    op.create_index(op.f("ix_post_rag_chunks_document_id"), "post_rag_chunks", ["document_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_post_rag_chunks_document_id"), table_name="post_rag_chunks")
    op.drop_index(op.f("ix_post_rag_chunks_post_id"), table_name="post_rag_chunks")
    op.drop_index(op.f("ix_post_rag_chunks_id"), table_name="post_rag_chunks")
    op.drop_table("post_rag_chunks")
