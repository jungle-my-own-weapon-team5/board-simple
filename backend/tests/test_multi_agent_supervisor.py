from collections.abc import Generator
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models import LegalDocument, LegalDocumentChunk, LegalSource, User
from app.models.embedding import EmbeddingProfile, LegalDocumentChunkEmbedding
from app.repositories import (
    agent_steps as agent_step_repository,
    document_chunks,
    embeddings as embedding_repository,
    legal_documents,
    rag_runs as rag_run_repository,
)
from app.services.agent.state import AgentRunRequest, LEGAL_AI_DISCLAIMER
from app.services.agent.supervisor import SupervisorAgent
from app.services.ai.types import (
    AITextRequest,
    AITextResult,
    EmbeddingRequest,
    EmbeddingResult,
)
from app.services.rag.normalization import calculate_text_checksum


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_supervisor_runs_specialized_agents_and_persists_handoff_audit(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    chunk_embedding = _create_chunk_embedding(
        db,
        profile=profile,
        title="보증금 반환 문서",
        heading="제1조",
        content="임대차 보증금 반환과 지연손해금에 관한 내용",
        embedding=[1.0, 0.0, 0.0],
    )
    ai_client = _AgentTestAIClient(
        embedding=[1.0, 0.0, 0.0],
        draft_text="전문 Agent workflow로 생성한 답변 초안입니다.",
    )
    facts = "임대차 보증금을 돌려받지 못했습니다."
    question = "내용증명 초안을 어떻게 잡아야 하나요?"

    result = SupervisorAgent(
        settings=_settings(),
        ai_client=ai_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts=facts,
            question=question,
            top_k=1,
        ),
    )

    rag_run = rag_run_repository.get_rag_run(db, result.run_id)
    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "completed"
    assert result.answer == "전문 Agent workflow로 생성한 답변 초안입니다."
    assert result.disclaimer == LEGAL_AI_DISCLAIMER
    assert result.agent_provider == "mock"
    assert result.agent_model_name == "agent-test-model"
    assert result.citations == [
        {
            "chunk_id": chunk_embedding.chunk_id,
            "title": "보증금 반환 문서",
            "source_url": "https://example.test/statute",
            "heading": "제1조",
            "rank": 1,
        }
    ]
    assert [tool_call.tool_name for tool_call in result.tool_calls] == [
        "search_legal_documents",
        "verify_citations",
    ]
    assert rag_run is not None
    assert rag_run.status == "completed"
    assert rag_run.run_type == "answer_draft"
    assert rag_run.answer == result.answer

    assert [step.step_type for step in steps] == [
        "agent_issue_spotting",
        "agent_retrieval",
        "multi_agent_execute_tool",
        "agent_legal_source",
        "agent_drafting",
        "multi_agent_execute_model",
        "agent_citation_verifier",
        "multi_agent_execute_tool",
        "agent_safety_review",
        "multi_agent_persist",
    ]
    assert steps[0].output_json is not None
    assert steps[0].output_json["handoff"]["next_agent"] == "retrieval"
    assert steps[4].output_json is not None
    assert "prompt" not in steps[4].output_json["output"]
    assert steps[4].output_json["output"]["prompt_length"] > 0
    assert "임대차 보증금" not in str(steps[4].output_json)
    assert steps[8].status == "completed"
    assert ai_client.text_requests[0].model == "agent-test-model"
    assert "임대차 보증금" in ai_client.text_requests[0].prompt


def test_supervisor_completes_with_insufficient_evidence_response(
    db: Session,
) -> None:
    user = _create_user(db)
    _create_profile(db, dimensions=3)
    ai_client = _AgentTestAIClient(embedding=[1.0, 0.0, 0.0])

    result = SupervisorAgent(
        settings=_settings(),
        ai_client=ai_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="dispute_issues",
            facts="관련 문서가 아직 없는 사실관계입니다.",
            question="검토할 쟁점이 있나요?",
            search_mode="issue_spotting",
            top_k=1,
        ),
    )

    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "completed"
    assert "citation 근거가 충분하지 않습니다" in (result.answer or "")
    assert result.citations == []
    assert [tool_call.tool_name for tool_call in result.tool_calls] == [
        "search_legal_documents"
    ]
    assert ai_client.text_requests == []
    assert "agent_safety_review" in [step.step_type for step in steps]
    assert "agent_citation_verifier" not in [step.step_type for step in steps]


def test_supervisor_stops_when_handoff_budget_is_exceeded(db: Session) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    _create_chunk_embedding(
        db,
        profile=profile,
        title="반복 제한 문서",
        heading="제2조",
        content="handoff 제한 테스트를 위한 문서 내용",
        embedding=[1.0, 0.0, 0.0],
    )
    ai_client = _AgentTestAIClient(embedding=[1.0, 0.0, 0.0])

    result = SupervisorAgent(
        settings=_settings(ai_agent_max_handoffs=1),
        ai_client=ai_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts="handoff 제한을 확인합니다.",
            question="검색 후 답변해주세요.",
            top_k=1,
        ),
    )

    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "failed"
    assert result.error_code == "supervisor_handoff_budget_exceeded"
    assert result.answer is None
    assert ai_client.text_requests == []
    assert steps[-1].step_type == "multi_agent_error"
    assert steps[-1].error_code == "supervisor_handoff_budget_exceeded"


def test_supervisor_fails_when_required_review_agents_would_be_skipped(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    _create_chunk_embedding(
        db,
        profile=profile,
        title="검증 필수 문서",
        heading="제3조",
        content="citation 검증과 safety review가 필요한 문서 내용",
        embedding=[1.0, 0.0, 0.0],
    )
    ai_client = _AgentTestAIClient(embedding=[1.0, 0.0, 0.0])

    result = SupervisorAgent(
        settings=_settings(ai_agent_max_iterations=4),
        ai_client=ai_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts="검증 단계를 건너뛰면 안 됩니다.",
            question="답변을 만들어주세요.",
            top_k=1,
        ),
    )

    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "failed"
    assert result.error_code == "supervisor_iteration_budget_exceeded"
    assert steps[-1].step_type == "multi_agent_error"
    assert "agent_citation_verifier" not in [step.step_type for step in steps]
    assert "multi_agent_persist" not in [step.step_type for step in steps]


def _settings(
    *,
    ai_agent_max_iterations: int = 6,
    ai_agent_max_tool_calls: int = 5,
    ai_agent_max_handoffs: int = 8,
) -> Settings:
    return Settings(
        app_env="test",
        ai_rag_enabled=False,
        ai_agent_provider="mock",
        ai_agent_model="agent-test-model",
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=3,
        ai_agent_max_iterations=ai_agent_max_iterations,
        ai_agent_max_tool_calls=ai_agent_max_tool_calls,
        ai_agent_max_handoffs=ai_agent_max_handoffs,
    )


class _AgentTestAIClient:
    def __init__(
        self,
        *,
        embedding: list[float],
        draft_text: str = "테스트 답변 초안입니다.",
    ) -> None:
        self.embedding = embedding
        self.draft_text = draft_text
        self.embedding_requests: list[EmbeddingRequest] = []
        self.text_requests: list[AITextRequest] = []

    def embed_texts(self, request: EmbeddingRequest) -> list[EmbeddingResult]:
        self.embedding_requests.append(request)
        return [
            EmbeddingResult(
                embedding=self.embedding,
                embedding_provider="mock",
                embedding_model_name=request.model,
                dimensions=len(self.embedding),
                input_index=0,
            )
        ]

    def generate_text(self, request: AITextRequest) -> AITextResult:
        self.text_requests.append(request)
        return AITextResult(
            text=self.draft_text,
            agent_provider="mock",
            agent_model_name=request.model,
            finish_reason="stop",
            raw_response_id="test-response-id",
        )


def _create_user(db: Session) -> User:
    user = User(
        email=f"multi-agent-user-{db.query(User).count()}@example.com",
        password_hash="hashed-password",
        nickname=f"multi-agent-user-{db.query(User).count()}",
    )
    db.add(user)
    db.flush()
    return user


def _create_profile(
    db: Session,
    *,
    dimensions: int,
    model_name: str = "mock-embedding",
    status: str = "active",
) -> EmbeddingProfile:
    return embedding_repository.get_or_create_embedding_profile(
        db,
        provider="mock",
        model_name=model_name,
        dimensions=dimensions,
        status=status,
        is_default=True,
    )


def _create_chunk_embedding(
    db: Session,
    *,
    profile: EmbeddingProfile,
    title: str,
    heading: str,
    content: str,
    embedding: list[float],
    document_type: str = "statute",
) -> LegalDocumentChunkEmbedding:
    source = LegalSource(
        provider="fixture",
        source_type=document_type,
        external_id=None,
        source_url=f"https://example.test/{document_type}",
    )
    legal_documents.add_legal_source(db, source)
    db.flush()

    document = LegalDocument(
        source_id=source.id,
        document_type=document_type,
        title=title,
        canonical_id=f"{document_type.upper()}-{db.query(LegalDocument).count() + 1}",
        version_label="2026-01-01",
        published_date=date(2025, 12, 1),
        effective_date=date(2026, 1, 1),
        raw_text=content,
        normalized_text=content,
        raw_checksum=calculate_text_checksum(content),
        normalized_checksum=calculate_text_checksum(content),
        dedup_status="unique",
        conflict_status="none",
        index_status="embedded",
    )
    legal_documents.add_legal_document(db, document)
    db.flush()

    chunk = LegalDocumentChunk(
        document_id=document.id,
        chunk_index=0,
        heading=heading,
        content=content,
        token_count=10,
        metadata_json={"fixture": "multi_agent"},
    )
    document_chunks.add_document_chunk(db, chunk)
    db.flush()

    chunk_embedding = LegalDocumentChunkEmbedding(
        chunk_id=chunk.id,
        embedding_profile_id=profile.id,
        embedding=embedding,
        embedding_status="embedded",
        content_checksum=calculate_text_checksum(content),
    )
    embedding_repository.add_chunk_embedding(db, chunk_embedding)
    db.flush()
    return chunk_embedding
