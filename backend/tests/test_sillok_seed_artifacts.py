from pathlib import Path

from scripts.build_sillok_seed_artifacts import artifact_paths, extract_inline_metadata, make_artifact, strip_seed_boilerplate


def test_make_artifact_splits_markdown_metadata_and_embedding_text(tmp_path: Path) -> None:
    manifest = {
        "seed_version": "sillok-v2-demo-500",
        "diagnostic_tag_policy": "diagnostic only",
    }
    record = {
        "selected_rank": 1,
        "seed_version": "sillok-v2-demo-500",
        "sillok_id": "kca_11711024_002",
        "source_url": "https://sillok.history.go.kr/id/kca_11711024_002",
        "period": "태종실록",
        "title": "태종실록: 세자가 금빛 고양이를 구하려 하다",
        "primary_bucket": "person_relation",
        "score": 15.9,
        "score_parts": {"person_relation": 8.1},
        "selection_reasons": ["person_relation", "title_clarity"],
        "evaluation_matches": ["yangnyeong_cat"],
    }
    source = {
        "source_material": "current_db",
        "title": record["title"],
        "period": "태종실록",
        "source_url": record["source_url"],
        "source_type": "sillok",
        "corpus": "",
        "metadata": {
            "date": "태종실록 33권, 태종 17년 10월 24일 계사 2/2 기사",
            "categories": "왕실-종친(宗親) / 과학-생물(生物)",
        },
        "content": "세자가 신효창의 집에 금빛 고양이를 구하니 탁신이 서연관에게 말하였다.",
    }
    paths = {
        "md": tmp_path / "md" / "태종실록" / "0001-kca_11711024_002.md",
        "metadata_json": tmp_path / "metadata_json" / "태종실록" / "0001-kca_11711024_002.json",
        "embedding_text": tmp_path / "embedding_text" / "태종실록" / "0001-kca_11711024_002.txt",
    }

    artifact = make_artifact(manifest, record, source, paths)

    assert "## 국역" in artifact["markdown"]
    assert artifact["metadata"]["selected_rank"] == 1
    assert artifact["metadata"]["king_year"] == 17
    assert artifact["metadata"]["month"] == 10
    assert artifact["metadata"]["article_no"] == 2
    assert artifact["metadata"]["content_hash"]
    assert artifact["metadata"]["categories"] == ["왕실-종친(宗親)", "과학-생물(生物)"]
    assert "이 문서는 태종실록의 조선왕조실록 기사이다." in artifact["embedding_text"]
    assert "평가용 진단 태그는 yangnyeong_cat이다." in artifact["embedding_text"]


def test_strip_seed_boilerplate_extracts_metadata_lines() -> None:
    content = """- 출전: 태종실록 33권, 태종 17년 10월 24일 계사 2/2 기사
- 기사 ID: kca_11711024_002
- URL: https://sillok.history.go.kr/id/kca_11711024_002
- 분류: 왕실-종친(宗親) / 과학-생물(生物)

세자가 신효창의 집에 금빛 고양이를 구하였다."""

    assert extract_inline_metadata(content) == {
        "date": "태종실록 33권, 태종 17년 10월 24일 계사 2/2 기사",
        "categories": "왕실-종친(宗親) / 과학-생물(生物)",
    }
    stripped = strip_seed_boilerplate(content)

    assert "출전:" not in stripped
    assert "기사 ID:" not in stripped
    assert "세자가 신효창" in stripped


def test_strip_seed_boilerplate_removes_trailing_classical_original_block() -> None:
    content = """예조에 전교하기를,

"상장의 모든 일은 의논하여 행하라."

하였다.

○傳于禮曹曰: "喪葬諸事, 同議行之。"
又曰: "此亦原文。"
"""

    stripped = strip_seed_boilerplate(content)

    assert "상장의 모든 일" in stripped
    assert "傳于禮曹" not in stripped
    assert "又曰" not in stripped


def test_artifact_paths_stay_under_one_seed_root(tmp_path: Path) -> None:
    paths = artifact_paths(
        tmp_path,
        {
            "selected_rank": 1,
            "sillok_id": "kca_11711024_002",
            "period": "태종실록",
        },
    )

    assert paths["md"] == tmp_path / "documents" / "태종실록" / "0001-kca_11711024_002.md"
    assert paths["metadata_json"] == tmp_path / "metadata_json" / "태종실록" / "0001-kca_11711024_002.json"
    assert paths["embedding_text"] == tmp_path / "embedding_text" / "태종실록" / "0001-kca_11711024_002.txt"
