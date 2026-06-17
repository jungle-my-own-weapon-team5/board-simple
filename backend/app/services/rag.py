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

RAG_SEARCH_CANDIDATE_MULTIPLIER = 3
MAX_RAG_CHUNKS_PER_POST = 2
RAG_MAX_COSINE_DISTANCE = 0.65


class RagNotConfiguredError(Exception):
    """RAG 실행에 필요한 설정이 없을 때 API 계층으로 전달하는 예외입니다."""

    pass


class RagGenerationError(Exception):
    """임베딩 생성이나 답변 생성처럼 외부 AI 호출이 실패했을 때 사용하는 예외입니다."""

    pass


@dataclass(frozen=True)
class RagSource:
    """프론트에서 답변 출처로 보여줄 게시글 청크 정보를 담습니다."""

    post_id: int
    title: str
    heading: str | None
    anchor: str | None
    snippet: str


@dataclass(frozen=True)
class RagAnswer:
    """RAG 챗봇의 최종 답변과 그 답변에 사용된 출처 목록입니다."""

    answer: str
    sources: list[RagSource]


@dataclass(frozen=True)
class RetrievedChunk:
    """벡터 검색으로 DB에서 찾아온 게시글 청크 원본입니다."""

    post_id: int
    title: str
    heading_path: str | None
    anchor: str | None
    content: str


def _get_openai_client(settings: Settings) -> OpenAI:
    """OpenAI API 키 설정을 확인하고 클라이언트를 생성합니다."""

    if not settings.openai_api_key:
        raise RagNotConfiguredError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def _embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    """문자열 목록을 현재 설정된 임베딩 모델의 벡터 목록으로 변환합니다.

    OpenAI Embeddings API는 입력 순서와 같은 순서로 결과를 돌려주므로,
    반환된 벡터는 같은 인덱스의 입력 텍스트와 짝을 맞춰 저장할 수 있습니다.
    """

    if not texts:
        return []
    client = _get_openai_client(settings)
    response = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    return [item.embedding for item in response.data]


def _post_tags(post: Post) -> list[str]:
    """게시글에 연결된 태그 이름만 RAG 임베딩 텍스트에 넣기 좋게 추출합니다."""

    return [tag.name for tag in post.tags]


def _has_same_chunks(
    existing_chunks: list[PostRagChunk],
    prepared_chunks: list[PreparedRagChunk],
    embedding_model: str,
) -> bool:
    """저장된 청크와 새로 만든 청크가 같은 임베딩 상태인지 확인합니다.

    청크 개수, 임베딩 모델, content_hash가 모두 같으면 게시글 내용/제목/태그가
    RAG 관점에서 변하지 않은 것이므로 OpenAI 임베딩 재생성을 건너뜁니다.
    """

    if len(existing_chunks) != len(prepared_chunks):
        return False
    return all(
        existing.embedding_model == embedding_model
        and existing.content_hash == prepared.content_hash
        for existing, prepared in zip(existing_chunks, prepared_chunks)
    )


def index_post_chunks(db: Session, post: Post) -> int:
    """게시글 하나를 RAG 검색용 청크로 나누고 임베딩해서 DB에 저장합니다.

    게시글 생성/수정 직후 호출되는 핵심 색인 함수입니다. 먼저 마크다운 본문을
    청크로 나누고, 제목/태그/헤딩/본문을 합친 embedding_text의 해시를 기존
    청크와 비교합니다. 변경이 없으면 비용이 드는 OpenAI 임베딩 호출을 하지
    않고 기존 청크 개수만 반환합니다.

    변경이 있으면 기존 청크를 지운 뒤 새 임베딩을 저장합니다. 단, API 키가
    없거나 OpenAI 호출이 실패하면 검색용 청크를 새로 만들 수 없으므로 0을
    반환합니다.
    """

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
    """기존 게시글들을 순회하면서 RAG 청크 색인을 다시 생성합니다.

    migration 이후 이미 존재하던 게시글을 검색 가능하게 만들 때 CLI에서
    사용합니다. 각 게시글 처리 후 commit해서 일부 게시글이 실패하더라도
    성공한 게시글 색인은 DB에 남깁니다.
    """

    posts = post_repository.list_posts_for_rag_backfill(db, post_ids=post_ids)
    results: list[tuple[int, int]] = []
    for post in posts:
        count = index_post_chunks(db, post)
        db.commit()
        results.append((post.id, count))
    return results


def _format_embedding_for_sql(embedding: list[float]) -> str:
    """pgvector의 CAST(:embedding AS vector)에 넣을 문자열 표현으로 변환합니다."""

    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def _limit_chunks_per_post(
    chunks: list[RetrievedChunk],
    *,
    total_limit: int,
) -> list[RetrievedChunk]:
    """RAG 컨텍스트에 같은 게시글 청크가 과도하게 들어가지 않도록 제한합니다."""

    post_counts: dict[int, int] = {}
    limited_chunks: list[RetrievedChunk] = []

    for chunk in chunks:
        if len(limited_chunks) >= total_limit:
            break

        current_count = post_counts.get(chunk.post_id, 0)
        if current_count >= MAX_RAG_CHUNKS_PER_POST:
            continue

        post_counts[chunk.post_id] = current_count + 1
        limited_chunks.append(chunk)

    return limited_chunks


def search_chunks(db: Session, question: str) -> list[RetrievedChunk]:
    """사용자 질문과 의미적으로 가까운 게시글 청크를 pgvector로 검색합니다.

    질문 자체를 임베딩한 뒤, 같은 임베딩 모델로 저장된 청크들과 cosine distance
    기준으로 비교합니다. 테스트에서 쓰는 SQLite 같은 비 PostgreSQL DB에서는
    vector 타입과 연산자를 사용할 수 없으므로 빈 결과를 반환합니다.
    """

    settings = get_settings()
    if not rag_chunk_repository.supports_vector_search(db):
        return []

    try:
        query_embedding = _embed_texts([question], settings)[0]
    except OpenAIError as exc:
        raise RagGenerationError("Failed to embed RAG question") from exc

    top_k = max(1, settings.rag_top_k)
    rows = rag_chunk_repository.search_chunks_by_embedding(
        db,
        embedding=_format_embedding_for_sql(query_embedding),
        embedding_model=settings.openai_embedding_model,
        limit=top_k * RAG_SEARCH_CANDIDATE_MULTIPLIER,
    )

    chunks = [
        RetrievedChunk(
            post_id=row.post_id,
            title=row.title,
            heading_path=row.heading_path,
            anchor=row.anchor,
            content=row.content,
        )
        for row in rows
        if row.cosine_distance <= RAG_MAX_COSINE_DISTANCE
    ]
    return _limit_chunks_per_post(chunks, total_limit=top_k)


def _source_from_chunk(chunk: RetrievedChunk) -> RagSource:
    """검색된 청크를 프론트가 보여줄 수 있는 출처 카드 데이터로 바꿉니다."""

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
    """LLM 프롬프트에 넣을 게시글 컨텍스트 문자열을 만듭니다.

    각 청크에 번호, 게시글 ID, 제목, 헤딩, 본문을 붙여 모델이 출처별 내용을
    구분할 수 있게 합니다. 답변은 이 컨텍스트 안의 내용만 사용하도록
    answer_question의 instructions에서 제한합니다.
    """

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
    """RAG 챗봇 질문 하나에 대한 답변과 출처를 생성합니다.

    처리 순서는 OpenAI 설정 확인, 질문 임베딩 기반 청크 검색, 출처 목록 생성,
    검색 컨텍스트를 포함한 Responses API 호출입니다. 검색 결과가 없으면 외부
    답변 생성을 하지 않고 고정 메시지를 반환합니다.
    """

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
