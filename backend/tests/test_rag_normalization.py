from app.models.ai import RagDocument
from app.services.ai_runtime import (
    _chunk_seed_content,
    _is_unique_seed_source_url,
    _metadata_relevance_boost,
    _normalize_for_rag_content,
    _parse_seed_markdown,
    _public_corpus_name,
    _rag_corpus_priority,
)


def test_normalize_for_rag_content_adds_korean_aliases() -> None:
    content = (
        "왜변이 일어난 후 조선정부는 大內·小貳殿을 제외하고 통교를 단절하였다. "
        "명종 2년 丁未約條를 체결하였다. 763)"
    )

    normalized = _normalize_for_rag_content(content)

    assert "대내씨(大內)" in normalized
    assert "소이전/소이씨(小貳殿)" in normalized
    assert "정미약조(丁未約條)" in normalized
    assert "763)" not in normalized


def test_normalize_for_rag_content_preserves_existing_aliases() -> None:
    content = "정미약조(丁未約條)는 대마도와의 통교 재개와 관련된다."

    normalized = _normalize_for_rag_content(content)

    assert normalized.count("정미약조") == 1
    assert "정미약조(丁未約條)" in normalized


def test_unique_seed_source_url_detection() -> None:
    assert _is_unique_seed_source_url("https://sillok.history.go.kr/id/kda_10101001_001")
    assert _is_unique_seed_source_url("https://contents.history.go.kr/front/nh/view.do?levelId=nh_022_0010")
    assert _is_unique_seed_source_url("https://encykorea.aks.ac.kr/Article/E0029857")
    assert not _is_unique_seed_source_url("https://sillok.history.go.kr")


def test_parse_seed_markdown_preserves_overview_metadata(tmp_path) -> None:
    path = tmp_path / "encykorea.md"
    path.write_text(
        """---
title: "세종"
period: "조선 전기"
source_type: "overview"
corpus: "encykorea"
source_url: "https://encykorea.aks.ac.kr/Article/E0029857"
article_id: "E0029857"
---

# 세종

## 검색용 요약

세종은 조선의 제4대 왕이다.
""",
        encoding="utf-8",
    )

    parsed = _parse_seed_markdown(path)

    assert parsed is not None
    assert parsed["title"] == "세종"
    assert parsed["source_type"] == "overview"
    assert parsed["corpus"] == "encykorea"
    assert "E0029857" in parsed["metadata_json"]


def test_overview_chunks_are_larger_than_primary_source_chunks() -> None:
    content = "\n\n".join(["가" * 500, "나" * 500, "다" * 500])

    assert len(_chunk_seed_content(content, "overview")) == 2
    assert len(_chunk_seed_content(content, "primary_source")) == 3


def test_rag_corpus_priority_uses_encykorea_before_legacy() -> None:
    assert _rag_corpus_priority("세종은 어떤 왕인가", "auto") == ["encykorea", ""]
    assert _rag_corpus_priority("세종 실록 원문 기록", "auto") == ["", "encykorea"]
    assert _rag_corpus_priority("세종", "all") == [None]
    assert _rag_corpus_priority("세종", "encykorea") == ["encykorea"]
    assert _rag_corpus_priority("세종", "legacy") == [""]
    assert _rag_corpus_priority("세종", "sinpyeon_hanguksa") == ["sinpyeon_hanguksa"]


def test_public_corpus_name_maps_internal_legacy_label() -> None:
    assert _public_corpus_name(None) == "all"
    assert _public_corpus_name("") == "legacy"
    assert _public_corpus_name("encykorea") == "encykorea"


def test_metadata_relevance_boost_uses_document_title() -> None:
    document = RagDocument(title="세종", period="조선 전기", source_url="")

    assert _metadata_relevance_boost("세종은 어떤 왕인가", document) == 0.18
    assert _metadata_relevance_boost("문종은 어떤 왕인가", document) == 0.0
