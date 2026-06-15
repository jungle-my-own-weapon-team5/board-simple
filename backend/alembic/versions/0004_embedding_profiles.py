"""add embedding profiles

Revision ID: 0004_embedding_profiles
Revises: 0003_rag_schema
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import UserDefinedType

revision: str = "0004_embedding_profiles"
down_revision: Union[str, None] = "0003_rag_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class Vector(UserDefinedType):
    """pgvector의 vector 컬럼을 migration에서 생성하기 위한 최소 타입입니다."""

    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        if self.dimensions is None:
            return "vector"
        return f"vector({self.dimensions})"


def upgrade() -> None:
    op.create_table(
        "embedding_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=150), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(length=30), nullable=False),
        sa.Column("vector_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
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
        sa.CheckConstraint(
            "dimensions > 0",
            name="ck_embedding_profiles_dimensions_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "model_name",
            "dimensions",
            "distance_metric",
            name="uq_embedding_profiles_provider_model_dimensions_metric",
        ),
    )
    op.create_index(
        "ix_embedding_profiles_status_default",
        "embedding_profiles",
        ["status", "is_default"],
    )

    op.create_table(
        "legal_document_chunk_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("embedding_profile_id", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column(
            "embedding_status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_error", sa.Text(), nullable=True),
        sa.Column("content_checksum", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["legal_document_chunks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_profile_id"],
            ["embedding_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chunk_id",
            "embedding_profile_id",
            name="uq_chunk_embeddings_chunk_profile",
        ),
    )
    op.create_index(
        "ix_chunk_embeddings_profile_status",
        "legal_document_chunk_embeddings",
        ["embedding_profile_id", "embedding_status"],
    )
    op.create_index(
        "ix_chunk_embeddings_chunk_id",
        "legal_document_chunk_embeddings",
        ["chunk_id"],
    )
    op.create_index(
        "ix_chunk_embeddings_content_checksum",
        "legal_document_chunk_embeddings",
        ["content_checksum"],
    )

    with op.batch_alter_table("rag_runs") as batch_op:
        batch_op.add_column(sa.Column("embedding_profile_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("embedding_dimensions", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_rag_runs_embedding_profile_id_embedding_profiles",
            "embedding_profiles",
            ["embedding_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("rag_retrievals") as batch_op:
        batch_op.add_column(sa.Column("chunk_embedding_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("embedding_profile_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_rag_retrievals_chunk_embedding_id_chunk_embeddings",
            "legal_document_chunk_embeddings",
            ["chunk_embedding_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_rag_retrievals_embedding_profile_id_embedding_profiles",
            "embedding_profiles",
            ["embedding_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_rag_retrievals_embedding_profile_type",
        "rag_retrievals",
        ["embedding_profile_id", "retrieval_type"],
    )

    with op.batch_alter_table("legal_document_chunks") as batch_op:
        batch_op.drop_column("embedding")
        batch_op.drop_column("embedding_status")
        batch_op.drop_column("embedded_at")
        batch_op.drop_column("embedding_error")


def downgrade() -> None:
    with op.batch_alter_table("legal_document_chunks") as batch_op:
        batch_op.add_column(sa.Column("embedding_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "embedding_status",
                sa.String(length=30),
                server_default="pending",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("embedding", Vector(1536), nullable=True))

    op.drop_index(
        "ix_rag_retrievals_embedding_profile_type",
        table_name="rag_retrievals",
    )
    with op.batch_alter_table("rag_retrievals") as batch_op:
        batch_op.drop_constraint(
            "fk_rag_retrievals_embedding_profile_id_embedding_profiles",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_rag_retrievals_chunk_embedding_id_chunk_embeddings",
            type_="foreignkey",
        )
        batch_op.drop_column("embedding_profile_id")
        batch_op.drop_column("chunk_embedding_id")

    with op.batch_alter_table("rag_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_rag_runs_embedding_profile_id_embedding_profiles",
            type_="foreignkey",
        )
        batch_op.drop_column("embedding_dimensions")
        batch_op.drop_column("embedding_profile_id")

    op.drop_index(
        "ix_chunk_embeddings_content_checksum",
        table_name="legal_document_chunk_embeddings",
    )
    op.drop_index(
        "ix_chunk_embeddings_chunk_id",
        table_name="legal_document_chunk_embeddings",
    )
    op.drop_index(
        "ix_chunk_embeddings_profile_status",
        table_name="legal_document_chunk_embeddings",
    )
    op.drop_table("legal_document_chunk_embeddings")

    op.drop_index(
        "ix_embedding_profiles_status_default",
        table_name="embedding_profiles",
    )
    op.drop_table("embedding_profiles")
