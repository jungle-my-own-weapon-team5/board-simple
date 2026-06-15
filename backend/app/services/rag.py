import logging
from dataclasses import dataclass

from openai import OpenAI, OpenAIError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.post import Post
from app.models.post_rag_chunk import PostRagChunk
from app.repositories import posts as post_repository
from app.repositories import rag_chunks as rag_chunk_repository
from app.rag.chunking import PreparedRagChunk, prepare_post_chunks

logger = logging.getLogger(__name__)


class RagNotConfiguredError(Exception):
    pass


class RagGenerationError(Exception):
    pass


@dataclass(frozen=True)
class RagSource:
    post_id: int
    title: str
    heading: str | None
    anchor: str | None
    snippet: str


@dataclass(frozen=True)
class RagAnswer:
    answer: str
    sources: list[RagSource]


@dataclass(frozen=True)
class RetrievedChunk:
    post_id: int
    title: str
    heading_path: str | None
    anchor: str | None
    content: str


def _get_openai_client(settings: Settings) -> OpenAI:
    if not settings.openai_api_key:
        raise RagNotConfiguredError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def _embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    if not texts:
        return []
    client = _get_openai_client(settings)
    response = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    return [item.embedding for item in response.data]


def _post_tags(post: Post) -> list[str]:
    return [tag.name for tag in post.tags]


def _has_same_chunks(
    existing_chunks: list[PostRagChunk],
    prepared_chunks: list[PreparedRagChunk],
    embedding_model: str,
) -> bool:
    if len(existing_chunks) != len(prepared_chunks):
        return False
    return all(
        existing.embedding_model == embedding_model
        and existing.content_hash == prepared.content_hash
        for existing, prepared in zip(existing_chunks, prepared_chunks)
    )


def index_post_chunks(db: Session, post: Post) -> int:
    settings = get_settings()
    prepared_chunks = prepare_post_chunks(post.title, _post_tags(post), post.content)
    existing_chunks = rag_chunk_repository.list_post_chunks(db, post.id)

    if _has_same_chunks(existing_chunks, prepared_chunks, settings.openai_embedding_model):
        return len(existing_chunks)

    rag_chunk_repository.delete_post_chunks(db, post.id)

    if not settings.openai_api_key or not prepared_chunks:
        return 0

    try:
        embeddings = _embed_texts(
            [chunk.embedding_text for chunk in prepared_chunks],
            settings,
        )
    except OpenAIError:
        logger.exception("Failed to embed post %s for RAG", post.id)
        return 0

    for chunk, embedding in zip(prepared_chunks, embeddings):
        rag_chunk_repository.create_post_chunk(
            db,
            post_id=post.id,
            chunk_index=chunk.chunk_index,
            heading_path=chunk.heading_path,
            anchor=chunk.anchor,
            content=chunk.content,
            content_hash=chunk.content_hash,
            embedding_model=settings.openai_embedding_model,
            embedding=embedding,
        )
    return len(prepared_chunks)


def backfill_post_chunks(db: Session, *, post_ids: list[int] | None = None) -> list[tuple[int, int]]:
    posts = post_repository.list_posts_for_rag_backfill(db, post_ids=post_ids)
    results: list[tuple[int, int]] = []
    for post in posts:
        count = index_post_chunks(db, post)
        db.commit()
        results.append((post.id, count))
    return results


def _format_embedding_for_sql(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def search_chunks(db: Session, question: str) -> list[RetrievedChunk]:
    settings = get_settings()
    if not rag_chunk_repository.supports_vector_search(db):
        return []

    try:
        query_embedding = _embed_texts([question], settings)[0]
    except OpenAIError as exc:
        raise RagGenerationError("Failed to embed RAG question") from exc

    rows = rag_chunk_repository.search_chunks_by_embedding(
        db,
        embedding=_format_embedding_for_sql(query_embedding),
        embedding_model=settings.openai_embedding_model,
        limit=max(1, settings.rag_top_k),
    )

    return [
        RetrievedChunk(
            post_id=row.post_id,
            title=row.title,
            heading_path=row.heading_path,
            anchor=row.anchor,
            content=row.content,
        )
        for row in rows
    ]


def _source_from_chunk(chunk: RetrievedChunk) -> RagSource:
    snippet = " ".join(chunk.content.split())
    if len(snippet) > 260:
        snippet = f"{snippet[:257]}..."
    heading = chunk.heading_path.split(" > ")[-1] if chunk.heading_path else None
    return RagSource(
        post_id=chunk.post_id,
        title=chunk.title,
        heading=heading,
        anchor=chunk.anchor,
        snippet=snippet,
    )


def _build_context(chunks: list[RetrievedChunk]) -> str:
    sections = []
    for index, chunk in enumerate(chunks, start=1):
        heading = f"\nHeading: {chunk.heading_path}" if chunk.heading_path else ""
        sections.append(
            f"[{index}] Post ID: {chunk.post_id}\n"
            f"Title: {chunk.title}{heading}\n"
            f"Content:\n{chunk.content}"
        )
    return "\n\n---\n\n".join(sections)


def answer_question(db: Session, question: str) -> RagAnswer:
    settings = get_settings()
    client = _get_openai_client(settings)
    chunks = search_chunks(db, question)
    sources = [_source_from_chunk(chunk) for chunk in chunks]

    if not chunks:
        return RagAnswer(
            answer="검색된 게시글 컨텍스트가 없습니다.",
            sources=[],
        )

    instructions = (
        "You answer questions about Board Simple posts. "
        "Use only the provided post context. "
        "If the context is not enough, say that the posts do not contain enough information. "
        "Answer in the same language as the user's question and keep the answer concise."
    )
    prompt = f"Question:\n{question}\n\nPost context:\n{_build_context(chunks)}"

    try:
        response = client.responses.create(
            model=settings.openai_chat_model,
            instructions=instructions,
            input=prompt,
            store=False,
        )
    except OpenAIError as exc:
        raise RagGenerationError("Failed to generate RAG answer") from exc

    answer = response.output_text.strip()
    if not answer:
        answer = "답변을 생성하지 못했습니다."
    return RagAnswer(answer=answer, sources=sources)
