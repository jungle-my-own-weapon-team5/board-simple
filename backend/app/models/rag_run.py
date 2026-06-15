"""RAG 실행 이력, agent 단계, 검색 근거를 저장하는 ORM 모델입니다."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RagRun(Base):
    """사용자 질의 1회에 대한 RAG 실행 단위입니다."""

    __tablename__ = "rag_runs"
    __table_args__ = (
        Index("ix_rag_runs_user_created_at", "user_id", "created_at"),
        Index("ix_rag_runs_status_created_at", "status", "created_at"),
        Index("ix_rag_runs_agent_provider_model", "agent_provider", "agent_model_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_type: Mapped[str] = mapped_column(String(50))
    query: Mapped[str] = mapped_column(Text)
    facts: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    answer: Mapped[str | None] = mapped_column(Text)
    disclaimer: Mapped[str | None] = mapped_column(Text)
    agent_provider: Mapped[str | None] = mapped_column(String(50))
    agent_model_name: Mapped[str | None] = mapped_column(String(100))
    embedding_provider: Mapped[str] = mapped_column(String(50))
    embedding_model_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # agent_steps는 plan/tool/draft/verify 같은 실행 과정을 순서대로 남깁니다.
    agent_steps = relationship(
        "AgentStep", back_populates="rag_run", cascade="all, delete-orphan"
    )
    # retrievals는 답변 생성에 사용된 chunk와 점수를 감사 가능하게 남깁니다.
    retrievals = relationship(
        "RagRetrieval", back_populates="rag_run", cascade="all, delete-orphan"
    )


class AgentStep(Base):
    """RAG agent가 수행한 개별 단계의 입력/출력 metadata를 저장합니다."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        # step_index는 하나의 실행 안에서 agent 진행 순서를 고정합니다.
        UniqueConstraint("rag_run_id", "step_index", name="uq_agent_steps_run_index"),
        Index("ix_agent_steps_run_step_type", "rag_run_id", "step_type"),
        Index("ix_agent_steps_tool_name_created_at", "tool_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rag_run_id: Mapped[int] = mapped_column(
        ForeignKey("rag_runs.id", ondelete="CASCADE")
    )
    step_index: Mapped[int] = mapped_column()
    step_type: Mapped[str] = mapped_column(String(50))
    tool_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # secret, raw JWT, provider API key는 이 JSON 필드에 저장하지 않아야 합니다.
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    rag_run = relationship("RagRun", back_populates="agent_steps")


class RagRetrieval(Base):
    """하나의 RAG 실행이 어떤 chunk를 어떤 순위로 참조했는지 저장합니다."""

    __tablename__ = "rag_retrievals"
    __table_args__ = (
        # 같은 실행에서 같은 chunk를 중복 근거로 기록하지 않습니다.
        UniqueConstraint("rag_run_id", "chunk_id", name="uq_rag_retrievals_run_chunk"),
        Index("ix_rag_retrievals_run_rank", "rag_run_id", "rank"),
        Index("ix_rag_retrievals_chunk_id", "chunk_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rag_run_id: Mapped[int] = mapped_column(
        ForeignKey("rag_runs.id", ondelete="CASCADE")
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("legal_document_chunks.id", ondelete="RESTRICT")
    )
    rank: Mapped[int] = mapped_column()
    score: Mapped[float | None] = mapped_column(Float)
    retrieval_type: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    rag_run = relationship("RagRun", back_populates="retrievals")
    chunk = relationship("LegalDocumentChunk")
