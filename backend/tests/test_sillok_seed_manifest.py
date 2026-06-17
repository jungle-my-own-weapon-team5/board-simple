from scripts.build_sillok_seed_manifest import build_manifest


def test_build_manifest_preserves_seed_fields_and_dedupe_keys() -> None:
    report = {
        "policy": {"target_total": 1},
        "periods": {
            "태종실록": [
                {
                    "sillok_id": "kca_11711024_002",
                    "source_url": "https://sillok.history.go.kr/id/kca_11711024_002",
                    "period": "태종실록",
                    "title": "세자가 금빛 고양이를 구하려 하다",
                    "primary_bucket": "person_relation",
                    "score": 15.9,
                    "selection_reasons": ["person_relation", "title_clarity"],
                    "evaluation_matches": ["yangnyeong_cat"],
                    "sort_key": "kca_11711024_002",
                }
            ]
        },
    }

    manifest = build_manifest(report, "sillok-v2-demo-500", "selected")
    record = manifest["records"][0]

    assert manifest["record_count"] == 1
    assert manifest["selected_count"] == 1
    assert manifest["total_candidates"] == 0
    assert manifest["diagnostic_tag_policy"]
    assert manifest["quality"]["duplicates"]["sillok_ids"] == []
    assert record["seed_version"] == "sillok-v2-demo-500"
    assert record["status"] == "selected"
    assert record["dedupe_keys"]["sillok_id"] == "kca_11711024_002"
    assert record["content_hash"] is None


def test_build_manifest_reports_duplicate_sillok_ids() -> None:
    report = {
        "periods": {
            "태종실록": [
                {"sillok_id": "dup", "source_url": "https://sillok.history.go.kr/id/dup_a"},
                {"sillok_id": "dup", "source_url": "https://sillok.history.go.kr/id/dup_b"},
            ]
        }
    }

    manifest = build_manifest(report, "sillok-v2-demo-500", "selected")

    assert manifest["quality"]["duplicates"]["sillok_ids"] == ["dup"]
