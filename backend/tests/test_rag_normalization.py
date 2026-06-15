from app.services.rag.normalization import (
    calculate_text_checksum,
    normalize_document_text,
    normalize_text,
)


def test_normalize_text_collapses_whitespace_and_blank_lines() -> None:
    raw_text = "  제1조\t 목적  \r\n\r\n\r\n 이 법은   테스트를\t정한다.  "

    assert normalize_text(raw_text) == "제1조 목적\n\n이 법은 테스트를 정한다."


def test_normalize_text_uses_unicode_nfc() -> None:
    decomposed = "\u1100\u1161"
    composed = "\uac00"

    assert normalize_text(decomposed) == composed
    assert calculate_text_checksum(normalize_text(decomposed)) == calculate_text_checksum(
        normalize_text(composed)
    )


def test_normalize_document_text_keeps_raw_and_normalized_checksums_separate() -> None:
    first = normalize_document_text("제1조   목적\r\n본문")
    second = normalize_document_text("제1조 목적\n본문")

    assert first.raw_text == "제1조   목적\r\n본문"
    assert first.normalized_text == "제1조 목적\n본문"
    assert first.raw_checksum != second.raw_checksum
    assert first.normalized_checksum == second.normalized_checksum


def test_normalize_document_text_handles_blank_input() -> None:
    result = normalize_document_text(" \r\n\t ")

    assert result.normalized_text == ""
    assert result.normalized_checksum == calculate_text_checksum("")
