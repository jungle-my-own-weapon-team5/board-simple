"""add rag schema

Revision ID: 0003_rag_schema
Revises: 0002_enable_pgvector
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import UserDefinedType

revision: str = "0003_rag_schema"
down_revision: Union[str, None] = "0002_enable_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class Vector(UserDefinedType):
    """pgvector의 vector(N) 컬럼을 migration에서 생성하기 위한 최소 타입입니다."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"


def upgrade() -> None:
    # 출처 -> 문서 -> chunk -> 실행 이력 순서로 생성해 foreign key 의존성을 맞춥니다.
    op.create_table(
        "legal_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_legal_sources_provider_source_type",
        "legal_sources",
        ["provider", "source_type"],
    )
    if op.get_bind().dialect.name == "postgresql":
        # SQLite는 부분 인덱스 옵션이 다르므로 운영 대상인 PostgreSQL에서만 생성합니다.
        op.create_index(
            "uq_legal_sources_provider_external_id",
            "legal_sources",
            ["provider", "external_id"],
            unique=True,
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )

    op.create_table(
        "legal_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("canonical_id", sa.String(length=255), nullable=True),
        sa.Column("version_label", sa.String(length=100), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("raw_checksum", sa.String(length=128), nullable=False),
        sa.Column("normalized_checksum", sa.String(length=128), nullable=True),
        sa.Column(
            "dedup_status",
            sa.String(length=30),
            server_default="unique",
            nullable=False,
        ),
        sa.Column(
            "conflict_status",
            sa.String(length=30),
            server_default="none",
            nullable=False,
        ),
        sa.Column("duplicate_of_document_id", sa.Integer(), nullable=True),
        sa.Column(
            "index_status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["source_id"], ["legal_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["duplicate_of_document_id"],
            ["legal_documents.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_legal_documents_document_type_published_date",
        "legal_documents",
        ["document_type", "published_date"],
    )
    op.create_index("ix_legal_documents_canonical_id", "legal_documents", ["canonical_id"])
    op.create_index(
        "ix_legal_documents_type_canonical_effective",
        "legal_documents",
        ["document_type", "canonical_id", "effective_date"],
    )
    op.create_index(
        "ix_legal_documents_type_canonical_version",
        "legal_documents",
        ["document_type", "canonical_id", "version_label"],
    )
    op.create_index("ix_legal_documents_raw_checksum", "legal_documents", ["raw_checksum"])
    op.create_index(
        "ix_legal_documents_normalized_checksum",
        "legal_documents",
        ["normalized_checksum"],
    )
    op.create_index(
        "ix_legal_documents_dedup_conflict",
        "legal_documents",
        ["dedup_status", "conflict_status"],
    )

    op.create_table(
        "legal_document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        # embedding dimension은 DB schema에 고정되므로 모델 변경 시 별도 migration이 필요합니다.
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "embedding_status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_error", sa.Text(), nullable=True),
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
            ["document_id"], ["legal_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_legal_document_chunks_document_id_chunk_index",
        ),
    )
    op.create_index(
        "ix_legal_document_chunks_document_id",
        "legal_document_chunks",
        ["document_id"],
    )

    op.create_table(
        "rag_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=50), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("facts", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("disclaimer", sa.Text(), nullable=True),
        sa.Column("agent_provider", sa.String(length=50), nullable=True),
        sa.Column("agent_model_name", sa.String(length=100), nullable=True),
        sa.Column("embedding_provider", sa.String(length=50), nullable=False),
        sa.Column("embedding_model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_runs_user_created_at", "rag_runs", ["user_id", "created_at"])
    op.create_index("ix_rag_runs_status_created_at", "rag_runs", ["status", "created_at"])
    op.create_index(
        "ix_rag_runs_agent_provider_model",
        "rag_runs",
        ["agent_provider", "agent_model_name"],
    )

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rag_run_id", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=50), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rag_run_id"], ["rag_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rag_run_id", "step_index", name="uq_agent_steps_run_index"),
    )
    op.create_index("ix_agent_steps_run_step_type", "agent_steps", ["rag_run_id", "step_type"])
    op.create_index(
        "ix_agent_steps_tool_name_created_at",
        "agent_steps",
        ["tool_name", "created_at"],
    )

    op.create_table(
        "rag_retrievals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rag_run_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("retrieval_type", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rag_run_id"], ["rag_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["legal_document_chunks.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rag_run_id", "chunk_id", name="uq_rag_retrievals_run_chunk"),
    )
    op.create_index("ix_rag_retrievals_run_rank", "rag_retrievals", ["rag_run_id", "rank"])
    op.create_index("ix_rag_retrievals_chunk_id", "rag_retrievals", ["chunk_id"])


def downgrade() -> None:
    # foreign key 의존성 때문에 생성 순서의 역순으로 삭제합니다.
    op.drop_index("ix_rag_retrievals_chunk_id", table_name="rag_retrievals")
    op.drop_index("ix_rag_retrievals_run_rank", table_name="rag_retrievals")
    op.drop_table("rag_retrievals")

    op.drop_index("ix_agent_steps_tool_name_created_at", table_name="agent_steps")
    op.drop_index("ix_agent_steps_run_step_type", table_name="agent_steps")
    op.drop_table("agent_steps")

    op.drop_index("ix_rag_runs_agent_provider_model", table_name="rag_runs")
    op.drop_index("ix_rag_runs_status_created_at", table_name="rag_runs")
    op.drop_index("ix_rag_runs_user_created_at", table_name="rag_runs")
    op.drop_table("rag_runs")

    op.drop_index(
        "ix_legal_document_chunks_document_id", table_name="legal_document_chunks"
    )
    op.drop_table("legal_document_chunks")

    op.drop_index("ix_legal_documents_dedup_conflict", table_name="legal_documents")
    op.drop_index("ix_legal_documents_normalized_checksum", table_name="legal_documents")
    op.drop_index("ix_legal_documents_raw_checksum", table_name="legal_documents")
    op.drop_index("ix_legal_documents_type_canonical_version", table_name="legal_documents")
    op.drop_index(
        "ix_legal_documents_type_canonical_effective", table_name="legal_documents"
    )
    op.drop_index("ix_legal_documents_canonical_id", table_name="legal_documents")
    op.drop_index(
        "ix_legal_documents_document_type_published_date",
        table_name="legal_documents",
    )
    op.drop_table("legal_documents")

    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(
            "uq_legal_sources_provider_external_id",
            table_name="legal_sources",
        )
    op.drop_index(
        "ix_legal_sources_provider_source_type",
        table_name="legal_sources",
    )
    op.drop_table("legal_sources")
