from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text

from app.core.database import get_session_local


CORPUS = "sillok-v2"
SOURCE_TYPE = "sillok"


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter live Sillok artifacts to the current DB shortage.")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-per-period", type=int, default=100)
    parser.add_argument("--min-content-length", type=int, default=80)
    parser.add_argument("--min-embedding-text-length", type=int, default=120)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    result = finalize_batch(
        source_dir=Path(args.source_dir),
        output_dir=Path(args.output_dir),
        target_per_period=args.target_per_period,
        min_content_length=args.min_content_length,
        min_embedding_text_length=args.min_embedding_text_length,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def finalize_batch(
    source_dir: Path,
    output_dir: Path,
    target_per_period: int,
    min_content_length: int,
    min_embedding_text_length: int,
    overwrite: bool,
) -> dict[str, Any]:
    manifest = read_json(source_dir / "manifest.json")
    records = manifest.get("records", [])
    if not records:
        raise SystemExit("manifest has no records")
    manifest_urls = {str(record.get("source_url") or "") for record in records}

    periods = {record.get("period", "") for record in records}
    if len(periods) != 1:
        raise SystemExit(f"expected one period in manifest, got: {sorted(periods)}")
    period = next(iter(periods))

    report_path = source_dir / "artifact_build_report.json"
    report = read_json(report_path) if report_path.exists() else {}
    current, existing_urls = load_db_state(period)
    need = max(0, target_per_period - current)

    eligible: list[tuple[int, dict[str, Any], Path]] = []
    rejected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for metadata_path in sorted((source_dir / "metadata_json").rglob("*.json")):
        metadata = read_json(metadata_path)
        relative = metadata_path.relative_to(source_dir / "metadata_json")
        embedding_path = source_dir / "embedding_text" / relative.with_suffix(".txt")
        document_path = source_dir / "documents" / relative.with_suffix(".md")
        embedding_text = embedding_path.read_text(encoding="utf-8").strip() if embedding_path.exists() else ""
        source_url = str(metadata.get("source_url") or "")
        reasons = rejection_reasons(
            metadata=metadata,
            expected_period=period,
            source_url=source_url,
            manifest_urls=manifest_urls,
            existing_urls=existing_urls,
            seen_urls=seen_urls,
            document_path=document_path,
            content_length=int(metadata.get("content_length") or 0),
            embedding_text_length=len(embedding_text),
            min_content_length=min_content_length,
            min_embedding_text_length=min_embedding_text_length,
        )
        if reasons:
            rejected.append(
                {
                    "path": str(metadata_path),
                    "sillok_id": metadata.get("sillok_id"),
                    "source_url": source_url,
                    "reason": reasons,
                    "content_length": metadata.get("content_length"),
                    "embedding_text_length": len(embedding_text),
                }
            )
            continue
        seen_urls.add(source_url)
        eligible.append((int(metadata.get("selected_rank") or 0), metadata, relative))

    eligible.sort(key=lambda item: item[0])
    selected = eligible[:need]
    if len(selected) < need:
        return write_report(
            output_dir,
            {
                "status": "insufficient_eligible",
                "period": period,
                "db_current_before": current,
                "target": target_per_period,
                "need": need,
                "eligible": len(eligible),
                "selected": len(selected),
                "rejected": len(rejected),
                "rejected_sample": rejected[:20],
            },
            overwrite,
        )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    for child in ["documents", "metadata_json", "embedding_text"]:
        (output_dir / child).mkdir(parents=True, exist_ok=True)

    selected_urls = {metadata["source_url"] for _, metadata, _ in selected}
    selected_records = [record for record in records if record.get("source_url") in selected_urls]
    next_manifest = {
        **manifest,
        "record_count": len(selected_records),
        "selected_count": len(selected_records),
        "records": selected_records,
        "filtered_from": str(source_dir),
        "filter_policy": {
            "period": period,
            "db_current_before": current,
            "target": target_per_period,
            "need": need,
            "min_content_length": min_content_length,
            "min_embedding_text_length": min_embedding_text_length,
            "exclude_existing_db_urls": True,
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(next_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for _, _, relative in selected:
        copy_artifact_triplet(source_dir, output_dir, relative)

    selected_content_lengths = [int(metadata.get("content_length") or 0) for _, metadata, _ in selected]
    selected_embedding_lengths = [
        len((source_dir / "embedding_text" / relative.with_suffix(".txt")).read_text(encoding="utf-8").strip())
        for _, _, relative in selected
    ]
    qa_report = {
        "schema_version": "sillok-final-artifact-filter-report-v1",
        "status": "finalized",
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "period": period,
        "db_current_before": current,
        "target": target_per_period,
        "need": need,
        "source_processed": report.get("processed"),
        "source_written": report.get("written"),
        "source_skipped": report.get("skipped"),
        "eligible": len(eligible),
        "selected": len(selected),
        "rejected": len(rejected),
        "selected_period_counts": dict(Counter(record.get("period", "") for record in selected_records)),
        "duplicates": {
            "source_urls": duplicated_values(record.get("source_url", "") for record in selected_records),
            "sillok_ids": duplicated_values(record.get("sillok_id", "") for record in selected_records),
        },
        "min_content_length": min(selected_content_lengths) if selected_content_lengths else None,
        "min_embedding_text_length": min(selected_embedding_lengths) if selected_embedding_lengths else None,
        "rejected_sample": rejected[:10],
    }
    (output_dir / "final_filter_report.json").write_text(
        json.dumps(qa_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return qa_report


def rejection_reasons(
    *,
    metadata: dict[str, Any],
    expected_period: str,
    source_url: str,
    manifest_urls: set[str],
    existing_urls: set[str],
    seen_urls: set[str],
    document_path: Path,
    content_length: int,
    embedding_text_length: int,
    min_content_length: int,
    min_embedding_text_length: int,
) -> list[str]:
    reasons = []
    if source_url not in manifest_urls:
        reasons.append("not_in_manifest")
    if metadata.get("period") != expected_period:
        reasons.append("wrong_period")
    if source_url in existing_urls:
        reasons.append("existing_db_url")
    if source_url in seen_urls:
        reasons.append("duplicate_source_url")
    if content_length < min_content_length:
        reasons.append("content_too_short")
    if embedding_text_length < min_embedding_text_length:
        reasons.append("embedding_text_too_short")
    if not document_path.exists():
        reasons.append("missing_markdown")
    return reasons


def load_db_state(period: str) -> tuple[int, set[str]]:
    db = get_session_local()()
    try:
        current = db.execute(
            text(
                "select count(*) from rag_documents "
                "where corpus=:corpus and source_type=:source_type and period=:period"
            ),
            {"corpus": CORPUS, "source_type": SOURCE_TYPE, "period": period},
        ).scalar() or 0
        urls = {
            row[0]
            for row in db.execute(
                text(
                    "select source_url from rag_documents "
                    "where corpus=:corpus and source_type=:source_type and source_url <> ''"
                ),
                {"corpus": CORPUS, "source_type": SOURCE_TYPE},
            ).fetchall()
        }
        return int(current), urls
    finally:
        db.close()


def copy_artifact_triplet(source_dir: Path, output_dir: Path, relative: Path) -> None:
    for child, suffix in [("metadata_json", ".json"), ("embedding_text", ".txt"), ("documents", ".md")]:
        source = source_dir / child / relative.with_suffix(suffix)
        target = output_dir / child / relative.with_suffix(suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def write_report(output_dir: Path, report: dict[str, Any], overwrite: bool) -> dict[str, Any]:
    if output_dir.exists() and not overwrite:
        raise SystemExit(f"output dir already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "final_filter_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def duplicated_values(values: Any) -> list[str]:
    counts = Counter(value for value in values if value)
    return sorted(value for value, count in counts.items() if count > 1)


if __name__ == "__main__":
    main()
