"""RAG 실행 이력 저장소 함수입니다."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.rag_run import AgentStep, RagRetrieval, RagRun


def add_rag_run(db: Session, rag_run: RagRun) -> None:
    """사용자 질의 1회에 대한 RAG 실행 row를 현재 트랜잭션에 추가합니다."""
    db.add(rag_run)


def get_rag_run(db: Session, rag_run_id: int) -> RagRun | None:
    return db.scalar(
        select(RagRun)
        .where(RagRun.id == rag_run_id)
        .options(
            selectinload(RagRun.agent_steps),
            selectinload(RagRun.retrievals),
        )
    )


def add_agent_step(db: Session, step: AgentStep) -> None:
    """agent의 개별 실행 단계를 현재 트랜잭션에 추가합니다."""
    db.add(step)


def add_rag_retrieval(db: Session, retrieval: RagRetrieval) -> None:
    """RAG 실행에서 참조한 검색 근거 chunk를 현재 트랜잭션에 추가합니다."""
    db.add(retrieval)


def list_agent_steps_by_run(db: Session, rag_run_id: int) -> list[AgentStep]:
    """RAG 실행의 agent step을 수행 순서대로 조회합니다.

    step_index 순서는 agent loop 재현과 디버깅의 기준입니다.
    """
    return list(
        db.scalars(
            select(AgentStep)
            .where(AgentStep.rag_run_id == rag_run_id)
            .order_by(AgentStep.step_index.asc())
        ).all()
    )


def list_retrievals_by_run(db: Session, rag_run_id: int) -> list[RagRetrieval]:
    """RAG 실행에서 참조한 chunk를 검색 순위대로 조회합니다.

    rank 순서는 사용자에게 노출할 근거 순서와 품질 평가에 사용됩니다.
    """
    return list(
        db.scalars(
            select(RagRetrieval)
            .where(RagRetrieval.rag_run_id == rag_run_id)
            .order_by(RagRetrieval.rank.asc())
        ).all()
    )
