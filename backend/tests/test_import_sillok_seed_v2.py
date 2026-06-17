import json
from pathlib import Path

from scripts.import_sillok_seed_v2 import SeedArtifact, duplicated_values, load_artifacts


def test_load_artifacts_pairs_metadata_document_and_embedding_text(tmp_path: Path) -> None:
    seed_dir = tmp_path / "sillok-v2-demo-500"
    period = "태종실록"
    stem = "0001-kca_11711024_002"
    metadata_dir = seed_dir / "metadata_json" / period
    document_dir = seed_dir / "documents" / period
    embedding_dir = seed_dir / "embedding_text" / period
    metadata_dir.mkdir(parents=True)
    document_dir.mkdir(parents=True)
    embedding_dir.mkdir(parents=True)
    metadata = {
        "sillok_id": "kca_11711024_002",
        "source_url": "https://sillok.history.go.kr/id/kca_11711024_002",
        "title": "태종실록: 세자가 금빛 고양이를 구하려 하다",
        "period": period,
    }
    (metadata_dir / f"{stem}.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    (document_dir / f"{stem}.md").write_text("# 문서", encoding="utf-8")
    (embedding_dir / f"{stem}.txt").write_text("검색용 텍스트", encoding="utf-8")

    artifacts = load_artifacts(seed_dir)

    assert artifacts == [
        SeedArtifact(
            sillok_id="kca_11711024_002",
            source_url="https://sillok.history.go.kr/id/kca_11711024_002",
            title="태종실록: 세자가 금빛 고양이를 구하려 하다",
            period=period,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            embedding_text="검색용 텍스트",
            document_markdown="# 문서",
        )
    ]


def test_duplicated_values_returns_repeated_items() -> None:
    assert duplicated_values(["a", "b", "a", "c", "b"]) == {"a", "b"}
