"""add strategy agent trace

Revision ID: 0008_strategy_agent_trace
Revises: 0007_langchain_openai_embeddings
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_strategy_agent_trace"
down_revision: Union[str, None] = "0007_langchain_openai_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("strategy_advices", sa.Column("agent_trace_json", sa.JSON(), nullable=False, server_default="[]"))
    op.alter_column("strategy_advices", "agent_trace_json", server_default=None)


def downgrade() -> None:
    op.drop_column("strategy_advices", "agent_trace_json")
