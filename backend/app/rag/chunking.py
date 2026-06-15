import hashlib
import re
import unicodedata
from dataclasses import dataclass

MAX_CHUNK_CHARS = 2200
CHUNK_OVERLAP_CHARS = 250
HEADING_ANCHOR_PREFIX = "user-content-"


@dataclass(frozen=True)
class RagChunkDraft:
    heading_path: str | None
    anchor: str | None
    content: str


@dataclass(frozen=True)
class PreparedRagChunk:
    chunk_index: int
    heading_path: str | None
    anchor: str | None
    content: str
    embedding_text: str
    content_hash: str


def _create_heading_slug(value: str) -> str:
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
    normalized = re.sub(r"\+\+([^+\n]+?)\+\+", r"\1", value)
    normalized = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"<[^>]*>", "", normalized)
    normalized = re.sub(r"\\([\\`*{}\[\]()#+\-.!_>])", r"\1", normalized)
    normalized = re.sub(r"[`*_~]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _create_heading_id_generator():
    seen: dict[str, int] = {}

    def create_heading_id(value: str) -> str:
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
    create_heading_id = _create_heading_id_generator()
    heading_stack: list[tuple[int, str]] = []
    sections: list[RagChunkDraft] = []
    current_heading_path: str | None = None
    current_anchor: str | None = None
    current_lines: list[str] = []
    is_inside_fence = False

    def flush_section() -> None:
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
    parts = [f"Title: {title}"]
    if tags:
        parts.append("Tags: " + ", ".join(f"#{tag}" for tag in tags))
    if heading_path:
        parts.append(f"Heading: {heading_path}")
    parts.append(f"Content:\n{content}")
    return "\n\n".join(parts)


def prepare_post_chunks(
    title: str,
    tags: list[str],
    content: str,
) -> list[PreparedRagChunk]:
    prepared_chunks: list[PreparedRagChunk] = []
    for index, chunk in enumerate(chunk_markdown(content)):
        embedding_text = build_embedding_text(
            title=title,
            tags=tags,
            heading_path=chunk.heading_path,
            content=chunk.content,
        )
        prepared_chunks.append(
            PreparedRagChunk(
                chunk_index=index,
                heading_path=chunk.heading_path,
                anchor=chunk.anchor,
                content=chunk.content,
                embedding_text=embedding_text,
                content_hash=hashlib.sha256(embedding_text.encode("utf-8")).hexdigest(),
            )
        )
    return prepared_chunks
