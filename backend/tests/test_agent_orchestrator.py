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
from app.services.agent.orchestrator import OrchestratorAgent
from app.services.agent.state import AgentAction, AgentRunRequest, LEGAL_AI_DISCLAIMER
from app.services.ai.errors import ProviderUnavailableError
from app.services.ai.types import (
    AITextRequest,
    AITextResult,
    EmbeddingRequest,
    EmbeddingResult,
)
from app.services.rag.legal_open_api import (
    LawOpenApiDocumentMetadata,
    LawOpenApiLawBody,
    LawOpenApiSearchItem,
    LawOpenApiSearchResult,
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


def test_orchestrator_agent_searches_drafts_verifies_and_persists_audit(
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
        draft_text="보증금 반환 청구 가능성을 검토한 초안입니다.",
    )
    settings = _settings(ai_agent_max_tool_calls=5)
    facts = "임대차 보증금을 돌려받지 못했습니다."
    question = "내용증명 초안을 어떻게 잡아야 하나요?"

    result = OrchestratorAgent(settings=settings, ai_client=ai_client).run(
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
    assert result.answer == "보증금 반환 청구 가능성을 검토한 초안입니다."
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
    assert rag_run.facts == facts
    assert rag_run.query == question
    assert rag_run.answer == result.answer
    assert rag_run.agent_provider == "mock"
    assert rag_run.agent_model_name == "agent-test-model"

    assert [step.step_type for step in steps] == [
        "initialize_run",
        "plan_issue_sources",
        "propose_action",
        "validate_action",
        "execute_tool",
        "observe",
        "decide_continue_or_stop",
        "draft",
        "propose_action",
        "validate_action",
        "verify",
        "persist",
    ]
    assert steps[1].input_json == {
        "task_type": "answer_draft",
        "facts_length": len(facts),
        "question_length": len(question),
        "search_mode": "focused_answer",
        "top_k": 1,
        "score_threshold": None,
        "max_chunks_per_document": None,
    }
    assert steps[2].output_json is not None
    assert steps[2].output_json["action_type"] == "search_internal"
    assert "임대차" not in str(steps[2].output_json)
    assert "임대차" not in str(steps[4].input_json)
    assert steps[4].input_json == {
        "search_mode": "focused_answer",
        "top_k": 1,
        "query_length": len(f"{facts}\n{question}"),
    }
    assert steps[10].status == "completed"
    assert steps[10].output_json == {"valid": True, "invalid_count": 0}
    assert ai_client.text_requests[0].model == "agent-test-model"
    assert "임대차 보증금" in ai_client.text_requests[0].prompt


def test_orchestrator_agent_stops_before_draft_when_tool_budget_is_exceeded(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    _create_chunk_embedding(
        db,
        profile=profile,
        title="쟁점 탐지 문서",
        heading="제2조",
        content="형사 쟁점 탐지를 위한 문서 내용",
        embedding=[1.0, 0.0, 0.0],
    )
    ai_client = _AgentTestAIClient(embedding=[1.0, 0.0, 0.0])

    result = OrchestratorAgent(
        settings=_settings(ai_agent_max_tool_calls=1),
        ai_client=ai_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="dispute_issues",
            facts="게시글 내용에서 여러 범죄 구성요건이 의심됩니다.",
            question="검토해야 할 쟁점을 찾아주세요.",
            search_mode="issue_spotting",
            top_k=1,
        ),
    )

    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "failed"
    assert result.error_code == "agent_tool_budget_exceeded"
    assert result.answer is None
    assert result.citations == []
    assert [tool_call.tool_name for tool_call in result.tool_calls] == [
        "search_legal_documents"
    ]
    assert len(ai_client.text_requests) == 1
    assert ai_client.text_requests[0].metadata == {"purpose": "legal_source_planner"}
    assert steps[-1].step_type == "error"
    assert steps[-1].error_code == "agent_tool_budget_exceeded"


def test_orchestrator_agent_syncs_official_source_when_internal_evidence_is_missing(
    db: Session,
) -> None:
    user = _create_user(db)
    _create_profile(db, dimensions=3)
    ai_client = _AgentTestAIClient(
        embedding=[1.0, 0.0, 0.0],
        draft_text="공식 법령을 보강해 검토한 초안입니다.",
    )
    law_client = _FakeLawOpenApiClient()

    result = OrchestratorAgent(
        settings=_settings(ai_agent_max_tool_calls=5, law_open_api_oc="test-oc"),
        ai_client=ai_client,
        law_open_api_client=law_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts="상대방이 돈을 받고 연락을 끊었습니다.",
            question="사기죄 관련 법령을 확인해 주세요.",
            top_k=3,
        ),
    )

    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "completed"
    assert result.answer == "공식 법령을 보강해 검토한 초안입니다."
    assert result.citations
    assert [tool_call.tool_name for tool_call in result.tool_calls] == [
        "search_legal_documents",
        "search_law_open_api",
        "search_legal_documents",
        "verify_citations",
    ]
    assert law_client.search_calls == ["사기죄 관련 법령을 확인해 주세요.", "형법"]
    assert law_client.body_calls == ["MST-CRIMINAL"]
    assert any(step.step_type == "execute_service" for step in steps)
    assert any(
        step.step_type == "observe"
        and step.output_json
        and step.output_json.get("after_official_source_sync") is True
        for step in steps
    )


def test_orchestrator_agent_syncs_when_internal_evidence_has_low_relevance(
    db: Session,
) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    _create_chunk_embedding(
        db,
        profile=profile,
        title="Wrong low-score statute",
        heading="Article 1",
        content="This internal chunk is unrelated to the user story.",
        embedding=[0.0, 0.0, 0.0],
    )
    ai_client = _AgentTestAIClient(
        embedding=[1.0, 0.0, 0.0],
        draft_text="Official source enriched answer",
    )
    law_client = _FakeLawOpenApiClient()

    result = OrchestratorAgent(
        settings=_settings(ai_agent_max_tool_calls=5, law_open_api_oc="test-oc"),
        ai_client=ai_client,
        law_open_api_client=law_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts="The landlord refuses to return the lease deposit.",
            question="Find the relevant legal basis.",
            top_k=3,
        ),
    )

    citation_titles = [citation["title"] for citation in result.citations]

    assert result.status == "completed"
    assert result.answer == "Official source enriched answer"
    assert "Wrong low-score statute" not in citation_titles
    assert result.citations
    assert [tool_call.tool_name for tool_call in result.tool_calls] == [
        "search_legal_documents",
        "search_law_open_api",
        "search_legal_documents",
        "verify_citations",
    ]


def test_orchestrator_agent_bootstraps_profile_before_official_source_sync(
    db: Session,
) -> None:
    user = _create_user(db)
    ai_client = _AgentTestAIClient(
        embedding=[1.0, 0.0, 0.0],
        draft_text="fresh DB에서도 공식 법령 보강 후 답변합니다.",
    )
    law_client = _FakeLawOpenApiClient()

    result = OrchestratorAgent(
        settings=_settings(ai_agent_max_tool_calls=5, law_open_api_oc="test-oc"),
        ai_client=ai_client,
        law_open_api_client=law_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts="공식 법령 corpus가 아직 비어 있는 fresh DB입니다.",
            question="관련 법령을 찾아 답변해 주세요.",
            top_k=3,
        ),
    )

    profiles = embedding_repository.list_active_embedding_profiles(db)

    assert result.status == "completed"
    assert result.answer == "fresh DB에서도 공식 법령 보강 후 답변합니다."
    assert result.citations
    assert len(profiles) == 1
    assert profiles[0].provider == "mock"
    assert profiles[0].model_name == "mock-embedding"
    assert profiles[0].is_default is True
    assert law_client.body_calls == ["MST-CRIMINAL"]


def test_orchestrator_agent_rejects_invalid_action_before_tool_execution(
    db: Session,
) -> None:
    user = _create_user(db)
    ai_client = _AgentTestAIClient(embedding=[1.0, 0.0, 0.0])

    result = OrchestratorAgent(
        settings=_settings(ai_agent_max_tool_calls=5),
        ai_client=ai_client,
        action_planner=_InvalidSearchToolPlanner(),
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts="잘못된 action 검증을 확인합니다.",
            question="검색을 실행해 주세요.",
            top_k=1,
        ),
    )

    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "failed"
    assert result.error_code == "agent_action_tool_mismatch"
    assert result.tool_calls == []
    assert ai_client.embedding_requests == []
    assert ai_client.text_requests == []
    assert steps[-1].step_type == "error"
    assert steps[-1].error_code == "agent_action_tool_mismatch"


def test_orchestrator_agent_sanitizes_provider_error_message(db: Session) -> None:
    user = _create_user(db)
    profile = _create_profile(db, dimensions=3)
    _create_chunk_embedding(
        db,
        profile=profile,
        title="provider 실패 문서",
        heading="제3조",
        content="provider 실패 테스트를 위한 문서 내용",
        embedding=[1.0, 0.0, 0.0],
    )
    ai_client = _AgentTestAIClient(
        embedding=[1.0, 0.0, 0.0],
        generation_error=ProviderUnavailableError("secret-like-provider-message"),
    )

    result = OrchestratorAgent(
        settings=_settings(ai_agent_max_tool_calls=5),
        ai_client=ai_client,
    ).run(
        db,
        AgentRunRequest(
            user_id=user.id,
            task_type="answer_draft",
            facts="provider 오류 메시지 저장 여부를 확인합니다.",
            question="답변 초안을 만들어주세요.",
            top_k=1,
        ),
    )

    rag_run = rag_run_repository.get_rag_run(db, result.run_id)
    steps = agent_step_repository.list_agent_steps_by_run(db, result.run_id)

    assert result.status == "failed"
    assert result.error_code == "ProviderUnavailableError"
    assert result.error_message == "ProviderUnavailableError"
    assert "secret-like-provider-message" not in str(result)
    assert rag_run is not None
    assert rag_run.error_message == "ProviderUnavailableError"
    assert steps[-1].step_type == "error"
    assert steps[-1].error_message == "ProviderUnavailableError"


def _settings(
    *,
    ai_agent_max_tool_calls: int = 5,
    law_open_api_oc: str = "",
) -> Settings:
    return Settings(
        app_env="test",
        ai_agent_provider="mock",
        ai_agent_model="agent-test-model",
        ai_source_planner_model="agent-test-model",
        ai_embedding_provider="mock",
        ai_embedding_model="mock-embedding",
        ai_embedding_dimensions=3,
        ai_agent_max_tool_calls=ai_agent_max_tool_calls,
        law_open_api_oc=law_open_api_oc,
    )


class _AgentTestAIClient:
    def __init__(
        self,
        *,
        embedding: list[float],
        draft_text: str = "테스트 답변 초안입니다.",
        generation_error: ProviderUnavailableError | None = None,
    ) -> None:
        self.embedding = embedding
        self.draft_text = draft_text
        self.generation_error = generation_error
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
        if self.generation_error is not None:
            raise self.generation_error
        return AITextResult(
            text=self.draft_text,
            agent_provider="mock",
            agent_model_name=request.model,
            finish_reason="stop",
            raw_response_id="test-response-id",
        )


class _InvalidSearchToolPlanner:
    def propose_search_action(self, request: AgentRunRequest) -> AgentAction:
        return AgentAction(
            action_type="search_internal",
            tool_name="verify_citations",
            arguments={"query": request.question, "search_mode": request.search_mode},
            reason="invalid_tool_for_search_action",
        )

    def propose_verify_action(
        self,
        *,
        rag_run_id: int,
        citations: list[dict[str, object]],
    ) -> AgentAction:
        return AgentAction(
            action_type="verify_citations",
            tool_name="verify_citations",
            arguments={"run_id": rag_run_id, "citations": citations},
            reason="unused",
        )


class _FakeLawOpenApiClient:
    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.body_calls: list[str] = []

    def search(
        self,
        *,
        query: str,
        target: str,
        limit: int = 5,
        page: int = 1,
        search_scope: int = 1,
    ) -> LawOpenApiSearchResult:
        self.search_calls.append(query)
        metadata = LawOpenApiDocumentMetadata(
            provider="law_open_api",
            provider_target="law",
            document_type="statute",
            title="형법",
            external_id="MST-CRIMINAL",
            canonical_id="LAW-CRIMINAL",
            version_label="2026-01-01",
            published_date=date(2025, 12, 1),
            effective_date=date(2026, 1, 1),
            source_url="https://www.law.go.kr/법령/형법",
            metadata_json={"fixture": "agent_sync"},
        )
        return LawOpenApiSearchResult(
            query=query,
            target="statute",
            external_target="law",
            page=page,
            limit=limit,
            total_count=1,
            items=[
                LawOpenApiSearchItem(
                    external_id="MST-CRIMINAL",
                    title="형법",
                    source_url="https://www.law.go.kr/법령/형법",
                    summary="형법 현행 법령",
                    target="statute",
                    metadata_json={"fixture": "agent_sync"},
                    preflight_metadata=metadata,
                )
            ],
        )

    def get_law_body(
        self,
        *,
        mst: str | None = None,
        law_id: str | None = None,
    ) -> LawOpenApiLawBody:
        self.body_calls.append(mst or law_id or "")
        return LawOpenApiLawBody(
            title="형법",
            raw_text="제347조(사기) 사람을 기망하여 재물의 교부를 받거나 재산상의 이익을 취득한 경우를 규정한다.",
            external_id="MST-CRIMINAL",
            law_id="LAW-CRIMINAL",
            mst="MST-CRIMINAL",
            source_url="https://www.law.go.kr/법령/형법",
            published_date=date(2025, 12, 1),
            effective_date=date(2026, 1, 1),
            version_label="2026-01-01",
            metadata_json={"fixture": "agent_sync"},
        )


def _create_user(db: Session) -> User:
    user = User(
        email=f"agent-user-{db.query(User).count()}@example.com",
        password_hash="hashed-password",
        nickname=f"agent-user-{db.query(User).count()}",
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
        metadata_json={"fixture": "agent"},
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
