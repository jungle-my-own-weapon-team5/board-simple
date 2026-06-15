"""RAG 문서 원문을 비교 가능한 텍스트와 checksum으로 변환합니다."""

from dataclasses import dataclass
import hashlib
import re
import unicodedata


HORIZONTAL_WHITESPACE_PATTERN = re.compile(r"[ \t\f\v]+")


@dataclass(frozen=True)
class NormalizedDocumentText:
    """수집 원문과 정규화 결과를 함께 들고 다니는 값 객체입니다."""

    raw_text: str
    normalized_text: str
    raw_checksum: str
    normalized_checksum: str


def calculate_text_checksum(text: str) -> str:
    """텍스트를 UTF-8 기준 SHA-256 checksum으로 변환합니다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(raw_text: str) -> str:
    """문서 비교와 검색에 사용할 수 있도록 공백과 줄바꿈을 정리합니다.

    원문 자체는 raw_text로 보존하고, 이 함수의 결과는 normalized_text와
    normalized_checksum 계산에만 사용합니다.
    """
    text = unicodedata.normalize("NFC", raw_text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    normalized_lines = [
        HORIZONTAL_WHITESPACE_PATTERN.sub(" ", line).strip()
        for line in text.split("\n")
    ]

    compact_lines: list[str] = []
    previous_line_was_blank = False
    for line in normalized_lines:
        if line == "":
            if compact_lines and not previous_line_was_blank:
                compact_lines.append("")
            previous_line_was_blank = True
            continue

        compact_lines.append(line)
        previous_line_was_blank = False

    while compact_lines and compact_lines[-1] == "":
        compact_lines.pop()

    return "\n".join(compact_lines)


def normalize_document_text(raw_text: str) -> NormalizedDocumentText:
    """원문, 정규화 본문, 두 checksum을 한 번에 계산합니다."""
    normalized_text = normalize_text(raw_text)
    return NormalizedDocumentText(
        raw_text=raw_text,
        normalized_text=normalized_text,
        raw_checksum=calculate_text_checksum(raw_text),
        normalized_checksum=calculate_text_checksum(normalized_text),
    )
