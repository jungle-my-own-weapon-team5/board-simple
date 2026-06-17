"""add rag document metadata

Revision ID: 0007_rag_document_metadata
Revises: 0006_post_thumbnail_url
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_rag_document_metadata"
down_revision: Union[str, None] = "0006_post_thumbnail_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column("source_type", sa.String(length=50), server_default="", nullable=False),
    )
    op.add_column(
        "rag_documents",
        sa.Column("corpus", sa.String(length=80), server_default="", nullable=False),
    )
    op.add_column("rag_documents", sa.Column("metadata_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rag_documents", "metadata_json")
    op.drop_column("rag_documents", "corpus")
    op.drop_column("rag_documents", "source_type")
