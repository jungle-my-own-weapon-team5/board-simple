"""정규화된 법률 문서를 RAG 검색용 chunk로 분리합니다."""

from dataclasses import dataclass
import re
from typing import Any


ARTICLE_HEADING_PATTERN = re.compile(
    r"^(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]*\))?)"
)
ARTICLE_BOUNDARY_PATTERN = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?\s*\([^)]*\)")
STRUCTURE_HEADING_PATTERN = re.compile(r"^제\s*\d+\s*(?:편|장|절|관)(?:\s+|$)")
TRAILING_STRUCTURE_HEADING_PATTERN = re.compile(
    r"^(?P<body>.+?)\s+(?P<structure>제\s*\d+\s*(?:편|장|절|관)\s+[^.。;；]+)$"
)
NORMALIZED_ARTICLE_HEADING_PATTERN = re.compile(r"^(제\d+조(?:의\d+)?)(?:\(([^)]*)\))?$")
CHUNKING_SCHEMA_VERSION = "article_boundary_v3"


@dataclass(frozen=True)
class ChunkingConfig:
    """chunk 길이와 overlap 정책입니다.

    이 값들은 검증된 최적값이 아니라 초기 baseline입니다. 호출자는 문서 유형별
    기본값을 쓰거나, ingestion/API 단계에서 명시적인 override 값을 전달할 수 있습니다.
    """

    min_chars: int
    max_chars: int
    overlap_chars: int
    merge_short_article_chunks: bool = False

    def validate(self) -> None:
        if self.min_chars < 0:
            raise ValueError("min_chars must be zero or positive")
        if self.max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if self.overlap_chars < 0:
            raise ValueError("overlap_chars must be zero or positive")
        if self.overlap_chars >= self.max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")
        if self.min_chars > self.max_chars:
            raise ValueError("min_chars must be smaller than or equal to max_chars")


@dataclass(frozen=True)
class TextChunk:
    """DB에 저장하기 전 단계의 문서 chunk 값 객체입니다."""

    chunk_index: int
    heading: str | None
    content: str
    token_count: int
    metadata_json: dict[str, Any]


@dataclass(frozen=True)
class _TextSection:
    """chunk 분할 전의 논리적 문서 구간입니다."""

    section_index: int
    heading: str | None
    lines: list[tuple[int, str]]
    strategy: str


@dataclass(frozen=True)
class _ChunkPart:
    """최종 chunk로 병합되기 전의 중간 chunk입니다."""

    heading: str | None
    content: str
    metadata_json: dict[str, Any]


FALLBACK_CHUNKING_CONFIG = ChunkingConfig(
    min_chars=150,
    max_chars=900,
    overlap_chars=90,
    merge_short_article_chunks=True,
)

# 문서 유형별 값은 답변 생성형 RAG를 위한 초기 profile입니다. 검증된 최적값이
# 아니므로 retrieval/citation 평가 fixture 결과에 따라 조정해야 합니다.
DOCUMENT_TYPE_CHUNKING_CONFIGS: dict[str, ChunkingConfig] = {
    "statute": ChunkingConfig(
        min_chars=0,
        max_chars=700,
        overlap_chars=80,
        merge_short_article_chunks=False,
    ),
    "case": ChunkingConfig(
        min_chars=250,
        max_chars=1200,
        overlap_chars=120,
        merge_short_article_chunks=True,
    ),
    "interpretation": ChunkingConfig(
        min_chars=200,
        max_chars=900,
        overlap_chars=90,
        merge_short_article_chunks=True,
    ),
    "admin_appeal": ChunkingConfig(
        min_chars=200,
        max_chars=1000,
        overlap_chars=100,
        merge_short_article_chunks=True,
    ),
    "user_file": ChunkingConfig(
        min_chars=150,
        max_chars=900,
        overlap_chars=90,
        merge_short_article_chunks=True,
    ),
    "memo": ChunkingConfig(
        min_chars=80,
        max_chars=500,
        overlap_chars=50,
        merge_short_article_chunks=True,
    ),
}


def get_chunking_config(
    document_type: str | None = None,
    *,
    override: ChunkingConfig | None = None,
) -> ChunkingConfig:
    """문서 유형별 chunking config를 반환합니다.

    override가 있으면 문서 유형 기본값보다 우선합니다. 알 수 없는 document_type은
    fallback profile을 사용합니다.
    """
    if override is not None:
        override.validate()
        return override

    if document_type is None:
        return FALLBACK_CHUNKING_CONFIG

    normalized_document_type = document_type.strip().lower()
    return DOCUMENT_TYPE_CHUNKING_CONFIGS.get(
        normalized_document_type, FALLBACK_CHUNKING_CONFIG
    )


def estimate_token_count(text: str) -> int:
    """실제 tokenizer 도입 전까지 사용할 보수적인 token 수 추정값입니다."""
    stripped_text = text.strip()
    if not stripped_text:
        return 0

    whitespace_units = len(stripped_text.split())
    character_units = max(1, len(stripped_text) // 4)
    return max(whitespace_units, character_units)


def extract_article_heading(line: str) -> str | None:
    """법령 조문 heading을 추출합니다."""
    match = ARTICLE_HEADING_PATTERN.match(line)
    if match is None:
        return None
    return re.sub(r"\s+", "", match.group(1))


def is_title_only_article_chunk(
    *,
    heading: str | None,
    content: str,
) -> bool:
    """조문 제목만 있고 실제 본문이 없는 chunk인지 판정합니다.

    짧은 조문 자체는 유효합니다. 예를 들어 "제1조(목적) 목적"처럼 heading 뒤에
    짧은 본문이 있으면 보존하고, "제52조(자수, 자복)"처럼 제목만 있는 경우만
    검색/인용 후보에서 제외하기 위한 기준입니다.
    """

    stripped_content = content.strip()
    if not stripped_content:
        return True

    if heading and _normalize_article_chunk_text(stripped_content) == (
        _normalize_article_chunk_text(heading)
    ):
        return True

    match = ARTICLE_HEADING_PATTERN.match(stripped_content)
    if match is None:
        return False
    remainder = stripped_content[match.end() :].strip()
    return not remainder


def has_article_boundary_contamination(
    *,
    heading: str | None,
    content: str,
) -> bool:
    """하나의 조문 chunk에 다음 조문 heading이 섞였는지 판정합니다."""

    if heading is None:
        return False
    normalized_heading = _normalize_article_chunk_text(heading)
    matches = list(ARTICLE_BOUNDARY_PATTERN.finditer(content))
    for match in matches[1:]:
        if _normalize_article_chunk_text(match.group(0)) != normalized_heading:
            return True
    return False


def chunk_document_text(
    text: str,
    *,
    document_type: str | None = None,
    config: ChunkingConfig | None = None,
) -> list[TextChunk]:
    """문서 유형별 기본값 또는 명시적 config로 문서를 chunking합니다."""
    resolved_config = get_chunking_config(document_type, override=config)
    return chunk_text(text, resolved_config)


def chunk_text(
    text: str, config: ChunkingConfig | None = None
) -> list[TextChunk]:
    """문서를 조문 또는 문단 단위의 안정적인 chunk 목록으로 나눕니다."""
    resolved_config = get_chunking_config(override=config)
    resolved_config.validate()

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    has_article_headings = any(extract_article_heading(line.strip()) for line in lines)
    if has_article_headings:
        # 국가법령정보 API 본문은 조문 경계가 한 줄 안에 붙는 경우가 있어,
        # article mode에서만 내부 조문 heading을 줄 경계로 승격합니다.
        lines = _split_inline_article_boundaries(lines)
    sections = (
        _split_article_sections(lines)
        if has_article_headings
        else _split_paragraph_sections(lines)
    )

    parts: list[_ChunkPart] = []
    for section in sections:
        content = _join_section_lines(section.lines)
        if not content:
            continue
        if section.heading is not None and is_title_only_article_chunk(
            heading=section.heading,
            content=content,
        ):
            continue
        if has_article_boundary_contamination(
            heading=section.heading,
            content=content,
        ):
            continue

        content_parts = _split_long_content(content, resolved_config)
        for part_index, content_part in enumerate(content_parts):
            parts.append(
                _ChunkPart(
                    heading=section.heading,
                    content=content_part,
                    metadata_json=_build_part_metadata(
                        section=section,
                        part_index=part_index,
                        part_count=len(content_parts),
                        config=resolved_config,
                    ),
                )
            )

    merged_parts = _merge_short_parts(parts, resolved_config)
    return [
        TextChunk(
            chunk_index=chunk_index,
            heading=part.heading,
            content=part.content,
            token_count=estimate_token_count(part.content),
            metadata_json=part.metadata_json,
        )
        for chunk_index, part in enumerate(merged_parts)
    ]


def _split_article_sections(lines: list[str]) -> list[_TextSection]:
    sections: list[_TextSection] = []
    current_heading: str | None = None
    current_lines: list[tuple[int, str]] = []
    current_strategy = "preamble"
    pending_structure_lines: list[tuple[int, str]] = []

    def flush_current() -> None:
        nonlocal current_lines
        trimmed_lines = _trim_blank_edges(current_lines)
        if trimmed_lines:
            sections.append(
                _TextSection(
                    section_index=len(sections),
                    heading=current_heading,
                    lines=trimmed_lines,
                    strategy=current_strategy,
                )
            )
        current_lines = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        heading = extract_article_heading(line) if line else None
        if line and STRUCTURE_HEADING_PATTERN.match(line):
            flush_current()
            pending_structure_lines.append((line_number, line))
            current_heading = None
            current_strategy = "preamble"
            continue

        if heading is not None:
            flush_current()
            current_heading = heading
            current_strategy = "article"
            if pending_structure_lines:
                current_lines.extend(pending_structure_lines)
                pending_structure_lines = []

        if line or current_lines:
            current_lines.append((line_number, line))

    if pending_structure_lines:
        current_heading = None
        current_strategy = "preamble"
        current_lines.extend(pending_structure_lines)
    flush_current()
    return sections


def _split_inline_article_boundaries(lines: list[str]) -> list[str]:
    expanded_lines: list[str] = []
    for raw_line in lines:
        expanded_lines.extend(_split_line_at_article_boundaries(raw_line))
    return expanded_lines


def _split_line_at_article_boundaries(raw_line: str) -> list[str]:
    line = raw_line.strip()
    if not line:
        return [raw_line]

    matches = list(ARTICLE_BOUNDARY_PATTERN.finditer(line))
    if len(matches) <= 1:
        return [raw_line]

    split_lines: list[str] = []
    start = 0
    for match in matches:
        if match.start() == start:
            continue
        previous = line[start : match.start()].strip()
        if previous:
            split_lines.extend(_split_trailing_structure_heading(previous))
        start = match.start()

    remainder = line[start:].strip()
    if remainder:
        split_lines.append(remainder)
    return split_lines or [raw_line]


def _split_trailing_structure_heading(line: str) -> list[str]:
    match = TRAILING_STRUCTURE_HEADING_PATTERN.match(line)
    if match is None:
        return [line]
    return [match.group("body").strip(), match.group("structure").strip()]


def _split_paragraph_sections(lines: list[str]) -> list[_TextSection]:
    sections: list[_TextSection] = []
    current_lines: list[tuple[int, str]] = []

    def flush_current() -> None:
        nonlocal current_lines
        if current_lines:
            sections.append(
                _TextSection(
                    section_index=len(sections),
                    heading=None,
                    lines=current_lines,
                    strategy="paragraph",
                )
            )
            current_lines = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if line:
            current_lines.append((line_number, line))
        else:
            flush_current()

    flush_current()
    return sections


def _join_section_lines(lines: list[tuple[int, str]]) -> str:
    return "\n".join(line for _, line in _trim_blank_edges(lines)).strip()


def _trim_blank_edges(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    start = 0
    end = len(lines)
    while start < end and lines[start][1] == "":
        start += 1
    while end > start and lines[end - 1][1] == "":
        end -= 1
    return lines[start:end]


def _split_long_content(content: str, config: ChunkingConfig) -> list[str]:
    stripped_content = content.strip()
    if len(stripped_content) <= config.max_chars:
        return [stripped_content] if stripped_content else []

    parts: list[str] = []
    start = 0
    while start < len(stripped_content):
        max_end = min(len(stripped_content), start + config.max_chars)
        if max_end == len(stripped_content):
            split_at = max_end
        else:
            split_at = start + _find_split_position(
                stripped_content[start : max_end + 1], config.max_chars
            )

        part = stripped_content[start:split_at].strip()
        if part:
            parts.append(part)
        if split_at >= len(stripped_content):
            break

        next_start = max(0, split_at - config.overlap_chars)
        if next_start <= start:
            next_start = split_at
        start = next_start

    return parts


def _find_split_position(content: str, max_chars: int) -> int:
    window = content[: max_chars + 1]
    minimum_position = max(1, max_chars // 2)

    for delimiter in ("\n\n", "\n", "다. ", ". ", " "):
        position = window.rfind(delimiter)
        if position >= minimum_position:
            return position + len(delimiter)

    return max_chars


def _merge_short_parts(
    parts: list[_ChunkPart], config: ChunkingConfig
) -> list[_ChunkPart]:
    if config.min_chars == 0:
        return parts

    merged_parts: list[_ChunkPart] = []
    index = 0
    while index < len(parts):
        buffer = [parts[index]]
        index += 1

        while (
            _combined_content_length(buffer) < config.min_chars
            and index < len(parts)
            and _can_merge_parts(buffer, parts[index], config)
        ):
            buffer.append(parts[index])
            index += 1

        merged_part = _merge_parts(buffer, config)
        if (
            _combined_content_length([merged_part]) < config.min_chars
            and merged_parts
            and _can_merge_parts([merged_parts[-1]], merged_part, config)
        ):
            previous_part = merged_parts.pop()
            merged_parts.append(_merge_parts([previous_part, merged_part], config))
        else:
            merged_parts.append(merged_part)

    return merged_parts


def _can_merge_parts(
    current_parts: list[_ChunkPart], next_part: _ChunkPart, config: ChunkingConfig
) -> bool:
    if _combined_content_length([*current_parts, next_part]) > config.max_chars:
        return False

    if config.merge_short_article_chunks:
        return True

    return not (
        any(_is_article_part(part) for part in current_parts)
        or _is_article_part(next_part)
    )


def _combined_content_length(parts: list[_ChunkPart]) -> int:
    if not parts:
        return 0
    return sum(len(part.content) for part in parts) + (len(parts) - 1) * 2


def _merge_parts(parts: list[_ChunkPart], config: ChunkingConfig) -> _ChunkPart:
    if len(parts) == 1:
        return parts[0]

    first_heading = next((part.heading for part in parts if part.heading), None)
    source_parts = [part.metadata_json for part in parts]
    source_anchors = [
        metadata["anchor"] for metadata in source_parts if "anchor" in metadata
    ]

    return _ChunkPart(
        heading=first_heading,
        content="\n\n".join(part.content for part in parts),
        metadata_json={
            "chunking_strategy": "merged",
            "chunking_schema_version": CHUNKING_SCHEMA_VERSION,
            "source_parts": source_parts,
            "source_anchors": source_anchors,
            "start_line": min(metadata["start_line"] for metadata in source_parts),
            "end_line": max(metadata["end_line"] for metadata in source_parts),
            "min_chars": config.min_chars,
            "max_chars": config.max_chars,
            "overlap_chars": config.overlap_chars,
        },
    )


def _is_article_part(part: _ChunkPart) -> bool:
    return part.metadata_json.get("chunking_strategy") == "article"


def _build_part_metadata(
    *,
    section: _TextSection,
    part_index: int,
    part_count: int,
    config: ChunkingConfig,
) -> dict[str, Any]:
    start_line = section.lines[0][0]
    end_line = section.lines[-1][0]
    anchor_value = (
        f"article:{section.heading}"
        if section.heading is not None
        else f"{section.strategy}:{section.section_index}"
    )

    metadata = {
        "chunking_strategy": section.strategy,
        "chunking_schema_version": CHUNKING_SCHEMA_VERSION,
        "section_index": section.section_index,
        "part_index": part_index,
        "part_count": part_count,
        "start_line": start_line,
        "end_line": end_line,
        "anchor": anchor_value,
        "min_chars": config.min_chars,
        "max_chars": config.max_chars,
        "overlap_chars": config.overlap_chars,
    }
    if section.heading is not None:
        metadata.update(_article_heading_metadata(section.heading))
    return metadata


def _article_heading_metadata(heading: str) -> dict[str, str]:
    match = NORMALIZED_ARTICLE_HEADING_PATTERN.match(heading)
    if match is None:
        return {"article_heading": heading}
    metadata = {
        "article_no": match.group(1),
        "article_heading": heading,
    }
    if match.group(2):
        metadata["article_title"] = match.group(2)
    return metadata


def _normalize_article_chunk_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()
