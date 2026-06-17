"""Add discussion topic cache table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_discussion_topics"
down_revision: str | None = "0007_rag_document_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discussion_topics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("topic_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("draft_title", sa.String(length=200), nullable=False),
        sa.Column("draft_content", sa.Text(), nullable=False),
        sa.Column("draft_post_type", sa.String(length=20), server_default="토론", nullable=False),
        sa.Column("draft_category", sa.String(length=50), server_default="오늘의 떡밥", nullable=False),
        sa.Column("citations_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("basis_post_id", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), server_default="0", nullable=False),
        sa.Column("generation_source", sa.String(length=50), server_default="local", nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["basis_post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_discussion_topics_id"), "discussion_topics", ["id"], unique=False)
    op.create_index(op.f("ix_discussion_topics_topic_date"), "discussion_topics", ["topic_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_discussion_topics_topic_date"), table_name="discussion_topics")
    op.drop_index(op.f("ix_discussion_topics_id"), table_name="discussion_topics")
    op.drop_table("discussion_topics")
