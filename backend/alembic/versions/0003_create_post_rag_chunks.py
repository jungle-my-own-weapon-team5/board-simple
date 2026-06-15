"""create post rag chunks

Revision ID: 0003_create_post_rag_chunks
Revises: 0002_enable_pgvector
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_create_post_rag_chunks"
down_revision: Union[str, None] = "0002_enable_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        embedding_type = Vector(1536)
    else:
        embedding_type = sa.JSON()

    op.create_table(
        "post_rag_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("anchor", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding", embedding_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "post_id", "chunk_index", name="uq_post_rag_chunks_post_id_chunk_index"
        ),
    )
    op.create_index(op.f("ix_post_rag_chunks_id"), "post_rag_chunks", ["id"], unique=False)
    op.create_index(
        op.f("ix_post_rag_chunks_post_id"),
        "post_rag_chunks",
        ["post_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_post_rag_chunks_content_hash"),
        "post_rag_chunks",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_post_rag_chunks_embedding_model"),
        "post_rag_chunks",
        ["embedding_model"],
        unique=False,
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_post_rag_chunks_embedding_cosine "
            "ON post_rag_chunks USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_post_rag_chunks_embedding_cosine")
    op.drop_index(op.f("ix_post_rag_chunks_embedding_model"), table_name="post_rag_chunks")
    op.drop_index(op.f("ix_post_rag_chunks_content_hash"), table_name="post_rag_chunks")
    op.drop_index(op.f("ix_post_rag_chunks_post_id"), table_name="post_rag_chunks")
    op.drop_index(op.f("ix_post_rag_chunks_id"), table_name="post_rag_chunks")
    op.drop_table("post_rag_chunks")
