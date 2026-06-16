import hashlib
import re
import unicodedata
from dataclasses import dataclass

MAX_CHUNK_CHARS = 2200
CHUNK_OVERLAP_CHARS = 250
HEADING_ANCHOR_PREFIX = "user-content-"


@dataclass(frozen=True) # 불변객체, __init__, __repr__, __eq__ 자동생성됨
class RagChunkDraft:
    """마크다운 본문에서 잘라낸 임베딩 전 단계의 청크입니다."""

    heading_path: str | None
    anchor: str | None # url id
    content: str


@dataclass(frozen=True)
class PreparedRagChunk:
    """DB 저장과 OpenAI 임베딩 요청에 필요한 형태로 정리된 RAG 청크입니다."""

    chunk_index: int
    heading_path: str | None
    anchor: str | None
    content: str
    embedding_text: str
    content_hash: str


def _create_heading_slug(value: str) -> str:
    """헤딩 텍스트를 URL fragment에 쓰기 좋은 slug로 바꿉니다."""

    normalized = unicodedata.normalize("NFKC", value.strip().lower())
    slug = "".join(
        char
        for char in normalized
        if char.isalnum() or char.isspace() or char == "-"
    )
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug or "section"


def _normalize_heading_text(value: str) -> str:
    """마크다운 헤딩 안의 링크, 이미지, 강조 표기 등을 사람이 읽는 텍스트로 정리합니다."""

    normalized = re.sub(r"\+\+([^+\n]+?)\+\+", r"\1", value)
    normalized = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"<[^>]*>", "", normalized)
    normalized = re.sub(r"\\([\\`*{}\[\]()#+\-.!_>])", r"\1", normalized)
    normalized = re.sub(r"[`*_~]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _create_heading_id_generator():
    """중복 헤딩에도 고유 anchor를 만들 수 있는 stateful 생성 함수를 반환합니다."""

    seen: dict[str, int] = {}

    def create_heading_id(value: str) -> str:
        """같은 slug가 반복되면 -2, -3 suffix를 붙여 고유 ID를 만듭니다."""

        slug = _create_heading_slug(value)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        return slug if count == 0 else f"{slug}-{count + 1}"

    return create_heading_id


def _split_long_text(
    content: str,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """긴 텍스트를 임베딩하기 적당한 크기의 청크 목록으로 나눕니다.

    기본적으로 빈 줄 기준 문단 단위로 합치되, max_chars를 넘으면 이전 청크의
    마지막 overlap_chars만큼을 다음 청크 앞에 다시 붙입니다. 이 overlap은
    경계 근처 문맥이 검색에서 사라지는 문제를 줄이기 위한 장치입니다.
    """

    if max_chars <= 0:
        return []
    overlap_chars = max(0, min(overlap_chars, max_chars - 1))

    text = content.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            step = max_chars - overlap_chars
            while start < len(paragraph):
                chunks.append(paragraph[start : start + max_chars].strip())
                if start + max_chars >= len(paragraph):
                    break
                start += step
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        chunks.append(current.strip())
        overlap = current[-overlap_chars:].strip()
        current = f"{overlap}\n\n{paragraph}" if overlap else paragraph
        if len(current) > max_chars:
            chunks.append(paragraph)
            current = ""

    if current:
        chunks.append(current.strip())

    return chunks


def chunk_markdown(content: str) -> list[RagChunkDraft]:
    """마크다운 본문을 헤딩 섹션 기준으로 RAG 청크로 나눕니다.

    H1부터 H3까지의 헤딩을 섹션 경계로 사용하고, fenced code block 안의
    # 문자는 헤딩으로 보지 않습니다. 헤딩이 전혀 없으면 전체 본문을 길이 기준
    청크로 나눕니다.
    """

    create_heading_id = _create_heading_id_generator()
    heading_stack: list[tuple[int, str]] = []
    sections: list[RagChunkDraft] = []
    current_heading_path: str | None = None
    current_anchor: str | None = None
    current_lines: list[str] = []
    is_inside_fence = False

    def flush_section() -> None:
        """현재까지 모은 섹션 본문을 길이 제한에 맞춰 sections에 추가합니다."""

        text = "\n".join(current_lines).strip()
        if not text:
            return
        for chunk in _split_long_text(text):
            sections.append(
                RagChunkDraft(
                    heading_path=current_heading_path,
                    anchor=current_anchor,
                    content=chunk,
                )
            )

    for line in content.splitlines():
        trimmed = line.strip()
        starts_fence = re.match(r"^(`{3,}|~{3,})", trimmed) is not None
        heading_match = None if is_inside_fence else re.match(r"^(#{1,3})\s+(.+?)\s*$", line)

        if starts_fence:
            is_inside_fence = not is_inside_fence

        if heading_match:
            flush_section()
            current_lines = []

            level = len(heading_match.group(1))
            heading_text = _normalize_heading_text(
                re.sub(r"\s+#+\s*$", "", heading_match.group(2))
            )
            if not heading_text:
                continue

            heading_stack = [
                (existing_level, text)
                for existing_level, text in heading_stack
                if existing_level < level
            ]
            heading_stack.append((level, heading_text))
            current_heading_path = " > ".join(text for _, text in heading_stack)
            current_anchor = f"{HEADING_ANCHOR_PREFIX}{create_heading_id(heading_text)}"
            continue

        current_lines.append(line)

    flush_section()

    if sections:
        return sections

    return [
        RagChunkDraft(heading_path=None, anchor=None, content=chunk)
        for chunk in _split_long_text(content)
    ]


def build_embedding_text(
    title: str,
    tags: list[str],
    heading_path: str | None,
    content: str,
) -> str:
    """임베딩에 사용할 텍스트를 제목, 태그, 헤딩, 본문 순서로 구성합니다.

    본문만 임베딩하면 검색어가 제목이나 태그와만 맞는 경우를 놓칠 수 있습니다.
    그래서 게시글의 메타데이터를 함께 넣어 의미 검색 품질을 높입니다.
    """

    parts = [f"Title: {title}"]
    if tags:
        parts.append("Tags: " + ", ".join(f"#{tag}" for tag in tags))
    if heading_path:
        parts.append(f"Heading: {heading_path}")
    parts.append(f"Content:\n{content}")
    return "\n\n".join(parts)


def _get_embedding_content_budget(
    title: str,
    tags: list[str],
    heading_path: str | None,
) -> int:
    """최종 embedding_text가 MAX_CHUNK_CHARS 안에 들어가도록 본문 예산을 계산합니다."""

    metadata_text = build_embedding_text(
        title=title,
        tags=tags,
        heading_path=heading_path,
        content="",
    )
    return max(1, MAX_CHUNK_CHARS - len(metadata_text))


def _build_bounded_embedding_text(
    title: str,
    tags: list[str],
    heading_path: str | None,
    content: str,
) -> str:
    """병적인 메타데이터 입력에서도 임베딩 요청 텍스트 길이를 상한 안에 둡니다."""

    embedding_text = build_embedding_text(
        title=title,
        tags=tags,
        heading_path=heading_path,
        content=content,
    )
    return embedding_text[:MAX_CHUNK_CHARS]


def prepare_post_chunks(
    title: str,
    tags: list[str],
    content: str,
) -> list[PreparedRagChunk]:
    """게시글 하나를 색인 가능한 RAG 청크 목록으로 변환합니다.

    각 청크마다 embedding_text를 만들고 그 값을 SHA-256으로 해시합니다.
    이 해시는 나중에 게시글이 RAG 관점에서 바뀌었는지 판단하는 캐시 키로
    사용됩니다.
    """

    prepared_chunks: list[PreparedRagChunk] = []
    for chunk in chunk_markdown(content):
        content_budget = _get_embedding_content_budget(title, tags, chunk.heading_path)
        overlap_chars = min(CHUNK_OVERLAP_CHARS, content_budget - 1)
        for content_chunk in _split_long_text(
            chunk.content,
            max_chars=content_budget,
            overlap_chars=overlap_chars,
        ):
            embedding_text = _build_bounded_embedding_text(
                title=title,
                tags=tags,
                heading_path=chunk.heading_path,
                content=content_chunk,
            )
            prepared_chunks.append(
                PreparedRagChunk(
                    chunk_index=len(prepared_chunks),
                    heading_path=chunk.heading_path,
                    anchor=chunk.anchor,
                    content=content_chunk,
                    embedding_text=embedding_text,
                    content_hash=hashlib.sha256(embedding_text.encode("utf-8")).hexdigest(),
                )
            )
    return prepared_chunks
