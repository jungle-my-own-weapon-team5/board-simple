import logging
from dataclasses import dataclass

from openai import OpenAI, OpenAIError
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.post import Post
from app.models.post_rag_chunk import PostRagChunk
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
    existing_chunks = db.scalars(
        select(PostRagChunk)
        .where(PostRagChunk.post_id == post.id)
        .order_by(PostRagChunk.chunk_index)
    ).all()

    if _has_same_chunks(existing_chunks, prepared_chunks, settings.openai_embedding_model):
        return len(existing_chunks)

    db.execute(delete(PostRagChunk).where(PostRagChunk.post_id == post.id))
    db.flush()

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
        db.add(
            PostRagChunk(
                post_id=post.id,
                chunk_index=chunk.chunk_index,
                heading_path=chunk.heading_path,
                anchor=chunk.anchor,
                content=chunk.content,
                content_hash=chunk.content_hash,
                embedding_model=settings.openai_embedding_model,
                embedding=embedding,
            )
        )
    db.flush()
    return len(prepared_chunks)


def _format_embedding_for_sql(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def search_chunks(db: Session, question: str) -> list[RetrievedChunk]:
    settings = get_settings()
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return []

    try:
        query_embedding = _embed_texts([question], settings)[0]
    except OpenAIError as exc:
        raise RagGenerationError("Failed to embed RAG question") from exc

    rows = db.execute(
        text(
            """
            SELECT
                chunks.post_id,
                posts.title,
                chunks.heading_path,
                chunks.anchor,
                chunks.content
            FROM post_rag_chunks AS chunks
            JOIN posts ON posts.id = chunks.post_id
            WHERE chunks.embedding_model = :embedding_model
            ORDER BY chunks.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {
            "embedding": _format_embedding_for_sql(query_embedding),
            "embedding_model": settings.openai_embedding_model,
            "limit": max(1, settings.rag_top_k),
        },
    ).mappings()

    return [
        RetrievedChunk(
            post_id=row["post_id"],
            title=row["title"],
            heading_path=row["heading_path"],
            anchor=row["anchor"],
            content=row["content"],
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
