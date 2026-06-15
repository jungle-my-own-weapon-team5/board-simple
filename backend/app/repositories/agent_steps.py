"""Agent step audit repository."""

from app.models.rag_run import AgentStep
from app.repositories import rag_runs as rag_run_repository
from sqlalchemy.orm import Session


def add_agent_step(db: Session, step: AgentStep) -> None:
    rag_run_repository.add_agent_step(db, step)


def list_agent_steps_by_run(db: Session, rag_run_id: int) -> list[AgentStep]:
    return rag_run_repository.list_agent_steps_by_run(db, rag_run_id)

