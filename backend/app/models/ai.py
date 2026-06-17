from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    period: Mapped[str] = mapped_column(String(80), default="", server_default="")
    source_url: Mapped[str] = mapped_column(String(500), default="", server_default="")
    source_type: Mapped[str] = mapped_column(String(50), default="", server_default="")
    corpus: Mapped[str] = mapped_column(String(80), default="", server_default="")
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AiResponse(Base):
    __tablename__ = "ai_responses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ToolLogRecord(Base):
    __tablename__ = "tool_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    result_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DiscussionTopicRecord(Base):
    __tablename__ = "discussion_topics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    topic_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    draft_title: Mapped[str] = mapped_column(String(200), nullable=False)
    draft_content: Mapped[str] = mapped_column(Text, nullable=False)
    draft_post_type: Mapped[str] = mapped_column(String(20), default="토론", server_default="토론")
    draft_category: Mapped[str] = mapped_column(String(50), default="오늘의 떡밥", server_default="오늘의 떡밥")
    citations_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    basis_post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    generation_source: Mapped[str] = mapped_column(String(50), default="local", server_default="local")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
