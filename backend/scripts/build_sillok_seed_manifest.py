from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deduplicated Sillok seed manifest from a candidate score report.")
    parser.add_argument("--input", required=True, help="Path to sillok_candidate_scores JSON report.")
    parser.add_argument("--output", required=True, help="Path to write manifest JSON.")
    parser.add_argument("--seed-version", default="sillok-v2-demo-500")
    parser.add_argument("--status", default="selected")
    args = parser.parse_args()

    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    manifest = build_manifest(report, args.seed_version, args.status)
    duplicates = manifest["quality"]["duplicates"]
    if duplicates["sillok_ids"] or duplicates["source_urls"]:
        Path(args.output).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"duplicate records found; manifest written for inspection: {Path(args.output).resolve()}", file=sys.stderr)
        sys.exit(2)

    output = Path(args.output)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"records={manifest['record_count']} manifest={output.resolve()}")


def build_manifest(report: dict[str, Any], seed_version: str, status: str) -> dict[str, Any]:
    records = flatten_records(report, seed_version, status)
    duplicates = find_duplicates(records)
    return {
        "schema_version": "sillok-seed-manifest-v1",
        "seed_version": seed_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "source": "current_db",
        "live_fetch": False,
        "scoring_script": "backend/scripts/score_sillok_article_candidates.py",
        "manifest_script": "backend/scripts/build_sillok_seed_manifest.py",
        "total_candidates": report.get("total_candidates", 0),
        "selected_count": len(records),
        "source_report_policy": report.get("policy", {}),
        "diagnostic_tag_policy": "evaluation_matches are diagnostic only and do not affect score, sorting, or selection.",
        "record_count": len(records),
        "quality": {
            "duplicate_key_policy": ["sillok_id", "source_url"],
            "duplicates": duplicates,
            "empty_sillok_id_count": sum(1 for record in records if not record["sillok_id"]),
            "empty_source_url_count": sum(1 for record in records if not record["source_url"]),
        },
        "records": records,
    }


def flatten_records(report: dict[str, Any], seed_version: str, status: str) -> list[dict[str, Any]]:
    records = []
    selected_rank = 1
    periods = report.get("periods", {})
    for period in sorted(periods):
        for item in periods[period]:
            records.append(
                {
                    "selected_rank": selected_rank,
                    "seed_version": seed_version,
                    "status": status,
                    "sillok_id": item.get("sillok_id") or source_url_id(item.get("source_url", "")),
                    "source_url": item.get("source_url", ""),
                    "period": item.get("period") or period,
                    "title": item.get("title", ""),
                    "primary_bucket": item.get("primary_bucket", ""),
                    "score": item.get("score", 0),
                    "score_parts": item.get("score_parts", {}),
                    "selection_reasons": item.get("selection_reasons", []),
                    "evaluation_matches": item.get("evaluation_matches", []),
                    "sort_key": item.get("sort_key", ""),
                    "content_hash": None,
                    "dedupe_keys": {
                        "sillok_id": item.get("sillok_id") or source_url_id(item.get("source_url", "")),
                        "source_url": item.get("source_url", ""),
                    },
                }
            )
            selected_rank += 1
    return records


def find_duplicates(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "sillok_ids": sorted(duplicated_values(record["sillok_id"] for record in records if record["sillok_id"])),
        "source_urls": sorted(duplicated_values(record["source_url"] for record in records if record["source_url"])),
    }


def duplicated_values(values: Any) -> set[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for value in values:
        if value in seen:
            duplicated.add(value)
        seen.add(value)
    return duplicated


def source_url_id(source_url: str) -> str:
    marker = "/id/"
    if marker not in source_url:
        return ""
    return source_url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0]


if __name__ == "__main__":
    main()
