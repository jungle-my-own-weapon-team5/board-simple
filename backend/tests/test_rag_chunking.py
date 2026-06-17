import pytest

from app.services.rag.chunking import (
    ChunkingConfig,
    chunk_document_text,
    chunk_text,
    estimate_token_count,
    extract_article_heading,
    get_chunking_config,
    is_title_only_article_chunk,
)
from app.services.rag.normalization import normalize_text


def test_extract_article_heading_normalizes_spacing() -> None:
    assert extract_article_heading("제 1 조 (목적) 이 법은 목적을 정한다.") == "제1조(목적)"
    assert extract_article_heading("제2조의2(정의)") == "제2조의2(정의)"
    assert extract_article_heading("부칙") is None


def test_get_chunking_config_returns_document_type_profile() -> None:
    statute_config = get_chunking_config("statute")
    memo_config = get_chunking_config("memo")
    case_config = get_chunking_config("case")

    assert statute_config.min_chars == 0
    assert statute_config.max_chars == 700
    assert statute_config.overlap_chars == 80
    assert statute_config.merge_short_article_chunks is False
    assert memo_config.max_chars == 500
    assert memo_config.min_chars == 80
    assert memo_config.overlap_chars == 50
    assert case_config.max_chars == 1200
    assert case_config.min_chars == 250
    assert case_config.overlap_chars == 120


def test_get_chunking_config_falls_back_for_unknown_document_type() -> None:
    config = get_chunking_config("unknown")

    assert config.min_chars == 150
    assert config.max_chars == 900
    assert config.overlap_chars == 90
    assert config.merge_short_article_chunks is True


def test_get_chunking_config_uses_override_before_document_type_profile() -> None:
    override = ChunkingConfig(
        min_chars=10,
        max_chars=90,
        overlap_chars=9,
        merge_short_article_chunks=True,
    )

    config = get_chunking_config("statute", override=override)

    assert config == override


def test_chunk_text_uses_fallback_config_when_document_type_is_not_provided() -> None:
    text = normalize_text(
        """
        제1조(목적)
        이 법은 테스트 목적을 정한다.

        제2조의2(정의)
        이 법에서 사용하는 용어의 뜻은 다음과 같다.
        """
    )

    chunks = chunk_text(text)

    assert [chunk.chunk_index for chunk in chunks] == [0]
    assert chunks[0].heading == "제1조(목적)"
    assert "제1조(목적)" in chunks[0].content
    assert "제2조의2(정의)" in chunks[0].content
    assert chunks[0].metadata_json["chunking_strategy"] == "merged"
    assert chunks[0].metadata_json["max_chars"] == 900
    assert chunks[0].metadata_json["min_chars"] == 150
    assert chunks[0].metadata_json["overlap_chars"] == 90


def test_chunk_document_text_applies_statute_profile() -> None:
    text = normalize_text(
        """
        제1조(목적)
        이 법은 테스트 목적을 정한다.

        제2조(정의)
        정의.
        """
    )

    chunks = chunk_document_text(text, document_type="statute")

    assert len(chunks) == 2
    assert chunks[0].metadata_json["max_chars"] == 700
    assert chunks[0].metadata_json["min_chars"] == 0
    assert chunks[0].metadata_json["overlap_chars"] == 80
    assert [chunk.heading for chunk in chunks] == ["제1조(목적)", "제2조(정의)"]
    assert chunks[0].metadata_json["chunking_schema_version"] == "article_boundary_v3"
    assert chunks[0].metadata_json["article_no"] == "제1조"
    assert chunks[0].metadata_json["article_title"] == "목적"


def test_chunk_document_text_splits_inline_article_boundaries() -> None:
    text = normalize_text(
        """
        제163조(변사체 검시 방해) 변사자의 시체를 은닉한 자는 벌금에 처한다. 제13장 방화와 실화의 죄 제164조(현주건조물등에의 방화) 불을 놓아 사람이 주거로 사용하는 건조물을 불태운 자는 처벌한다.
        """
    )

    chunks = chunk_document_text(text, document_type="statute")

    assert [chunk.heading for chunk in chunks] == [
        "제163조(변사체검시방해)",
        "제164조(현주건조물등에의방화)",
    ]
    assert "제164조" not in chunks[0].content
    assert "현주건조물" not in chunks[0].content
    assert "불을 놓아" not in chunks[0].content
    assert "제13장 방화와 실화의 죄" not in chunks[0].content
    assert "제13장 방화와 실화의 죄" in chunks[1].content
    assert chunks[1].metadata_json["article_no"] == "제164조"
    assert chunks[1].metadata_json["article_title"] == "현주건조물등에의방화"


def test_chunk_document_text_skips_title_only_article_chunks() -> None:
    text = normalize_text(
        """
        제52조(자수, 자복)

        제53조(정상참작감경)
        범죄의 정상에 참작할 만한 사유가 있는 때에는 그 형을 감경할 수 있다.
        """
    )

    chunks = chunk_document_text(text, document_type="statute")

    assert [chunk.heading for chunk in chunks] == ["제53조(정상참작감경)"]
    assert "제52조" not in chunks[0].content
    assert is_title_only_article_chunk(
        heading="제52조(자수, 자복)",
        content="제52조(자수, 자복)",
    )
    assert not is_title_only_article_chunk(
        heading="제1조(목적)",
        content="제1조(목적) 목적.",
    )


def test_chunk_document_text_applies_memo_profile() -> None:
    text = normalize_text(
        """
        첫 번째 메모입니다.

        두 번째 메모입니다.
        """
    )

    chunks = chunk_document_text(text, document_type="memo")

    assert chunks[0].metadata_json["min_chars"] == 80
    assert chunks[0].metadata_json["max_chars"] == 500
    assert chunks[0].metadata_json["overlap_chars"] == 50


def test_chunk_document_text_can_override_document_type_profile() -> None:
    text = "제1조(목적)\n" + ("가" * 120)
    override = ChunkingConfig(min_chars=0, max_chars=50, overlap_chars=10)

    chunks = chunk_document_text(text, document_type="statute", config=override)

    assert len(chunks) > 1
    assert all(chunk.metadata_json["max_chars"] == 50 for chunk in chunks)
    assert all(chunk.metadata_json["overlap_chars"] == 10 for chunk in chunks)
    assert chunks[0].content[-10:] == chunks[1].content[:10]


def test_chunk_text_keeps_short_article_chunks_separate_by_default() -> None:
    text = normalize_text(
        """
        제1조(목적)
        목적.

        제2조(정의)
        정의.
        """
    )
    config = ChunkingConfig(min_chars=200, max_chars=1200, overlap_chars=120)

    chunks = chunk_text(text, config)

    assert len(chunks) == 2
    assert [chunk.heading for chunk in chunks] == ["제1조(목적)", "제2조(정의)"]


def test_chunk_text_can_merge_short_article_chunks_when_configured() -> None:
    text = normalize_text(
        """
        제1조(목적)
        목적.

        제2조(정의)
        정의.
        """
    )
    config = ChunkingConfig(
        min_chars=200,
        max_chars=1200,
        overlap_chars=120,
        merge_short_article_chunks=True,
    )

    chunks = chunk_text(text, config)

    assert len(chunks) == 1
    assert chunks[0].heading == "제1조(목적)"
    assert "제2조(정의)" in chunks[0].content
    assert chunks[0].metadata_json["chunking_strategy"] == "merged"
    assert chunks[0].metadata_json["source_anchors"] == [
        "article:제1조(목적)",
        "article:제2조(정의)",
    ]


def test_chunk_text_falls_back_to_paragraphs_without_article_heading() -> None:
    text = normalize_text(
        """
        첫 번째 문단입니다.
        이어지는 같은 문단입니다.

        두 번째 문단입니다.
        """
    )
    config = ChunkingConfig(min_chars=0, max_chars=1200, overlap_chars=0)

    chunks = chunk_text(text, config)

    assert [chunk.content for chunk in chunks] == [
        "첫 번째 문단입니다.\n이어지는 같은 문단입니다.",
        "두 번째 문단입니다.",
    ]
    assert chunks[0].heading is None
    assert chunks[0].metadata_json["anchor"] == "paragraph:0"
    assert chunks[1].metadata_json["anchor"] == "paragraph:1"


def test_chunk_text_merges_short_paragraph_chunks_to_reach_min_chars() -> None:
    text = normalize_text(
        """
        첫 문단입니다.

        둘째 문단입니다.

        셋째 문단입니다.
        """
    )
    config = ChunkingConfig(min_chars=40, max_chars=200, overlap_chars=0)

    chunks = chunk_text(text, config)

    assert len(chunks) == 1
    assert chunks[0].content == "첫 문단입니다.\n\n둘째 문단입니다.\n\n셋째 문단입니다."
    assert chunks[0].metadata_json["chunking_strategy"] == "merged"
    assert chunks[0].metadata_json["source_anchors"] == [
        "paragraph:0",
        "paragraph:1",
        "paragraph:2",
    ]


def test_chunk_text_splits_long_content_with_overlap_and_stable_indexes() -> None:
    text = "제1조(목적)\n" + ("가" * 120)
    config = ChunkingConfig(min_chars=0, max_chars=50, overlap_chars=10)

    chunks = chunk_text(text, config)

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.content) <= 50 for chunk in chunks)
    assert chunks[0].content[-10:] == chunks[1].content[:10]
    assert all(chunk.heading == "제1조(목적)" for chunk in chunks)
    assert [chunk.metadata_json["part_index"] for chunk in chunks] == list(
        range(len(chunks))
    )
    assert all(chunk.metadata_json["overlap_chars"] == 10 for chunk in chunks)


def test_chunk_text_returns_empty_list_for_blank_text() -> None:
    assert chunk_text(" \n\n\t ") == []


def test_estimate_token_count_handles_blank_and_non_blank_text() -> None:
    assert estimate_token_count(" \n ") == 0
    assert estimate_token_count("짧은 문장입니다.") > 0


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            ChunkingConfig(min_chars=-1, max_chars=100, overlap_chars=10),
            "min_chars must be zero or positive",
        ),
        (
            ChunkingConfig(min_chars=0, max_chars=0, overlap_chars=0),
            "max_chars must be positive",
        ),
        (
            ChunkingConfig(min_chars=0, max_chars=100, overlap_chars=-1),
            "overlap_chars must be zero or positive",
        ),
        (
            ChunkingConfig(min_chars=0, max_chars=100, overlap_chars=100),
            "overlap_chars must be smaller than max_chars",
        ),
        (
            ChunkingConfig(min_chars=101, max_chars=100, overlap_chars=0),
            "min_chars must be smaller than or equal to max_chars",
        ),
    ],
)
def test_chunk_text_rejects_invalid_config(
    config: ChunkingConfig, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        chunk_text("본문", config)
