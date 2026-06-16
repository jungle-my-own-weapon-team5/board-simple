"""add ai rag tables

Revision ID: 0004_ai_rag_tables
Revises: 0003_post_discussion_fields
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_ai_rag_tables"
down_revision: Union[str, None] = "0003_post_discussion_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rag_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("period", sa.String(length=80), server_default="", nullable=False),
        sa.Column("source_url", sa.String(length=500), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rag_documents_id"), "rag_documents", ["id"], unique=False)

    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["rag_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rag_chunks_id"), "rag_chunks", ["id"], unique=False)

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE rag_chunks ADD COLUMN embedding vector(1536)")

    op.create_table(
        "ai_responses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.String(length=50), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_responses_id"), "ai_responses", ["id"], unique=False)

    op.create_table(
        "tool_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("result_summary", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_logs_id"), "tool_logs", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tool_logs_id"), table_name="tool_logs")
    op.drop_table("tool_logs")
    op.drop_index(op.f("ix_ai_responses_id"), table_name="ai_responses")
    op.drop_table("ai_responses")
    op.drop_index(op.f("ix_rag_chunks_id"), table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_index(op.f("ix_rag_documents_id"), table_name="rag_documents")
    op.drop_table("rag_documents")
