from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_session_local
from app.models.ai import RagDocument
from scripts.fetch_sillok_seed import RECORDS, collect_article_refs, slugify


PERIOD_TO_CODE = {record_name: code for code, record_name in RECORDS}


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect live Sillok article-id candidates for sillok-v2 expansion.")
    parser.add_argument("--plan", default="../sillok_v2_expansion_plan_to_100.json")
    parser.add_argument("--existing-manifest", default="../sillok_v2_expansion_manifest_to_100.json")
    parser.add_argument("--output", default="../sillok_v2_live_candidate_manifest.json")
    parser.add_argument("--cache-dir", default="../sillok_live_ref_cache")
    parser.add_argument("--target-per-period", type=int, default=100)
    parser.add_argument("--candidate-multiplier", type=int, default=4)
    parser.add_argument("--ref-fetch-limit", type=int, default=400)
    parser.add_argument("--limit-periods", type=int, default=0)
    parser.add_argument("--fetch-refs", action="store_true")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    existing_urls = load_existing_urls(Path(args.existing_manifest))
    db = get_session_local()()
    try:
        existing_urls.update(load_db_urls(db))
        db_period_counts = load_db_period_counts(db)
    finally:
        db.close()

    shortages = shortage_periods(plan, args.limit_periods, db_period_counts, args.target_per_period)
    records = []
    period_reports = {}
    cache_dir = Path(args.cache_dir)
    for period, shortage in shortages:
        code = PERIOD_TO_CODE.get(period)
        if not code:
            period_reports[period] = {"status": "unknown_period", "remaining_after_legacy": shortage}
            continue
        wanted = max(shortage * args.candidate_multiplier, shortage)
        if not args.fetch_refs:
            period_reports[period] = {
                "status": "dry_run",
                "record_code": code,
                "remaining_after_legacy": shortage,
                "wanted_candidates": wanted,
            }
            continue

        record_cache_dir = cache_dir / f"{code}-{slugify(period)}"
        record_cache_dir.mkdir(parents=True, exist_ok=True)
        refs = collect_article_refs(code, args.ref_fetch_limit, args.delay, record_cache_dir)
        selected_refs = select_time_distributed_refs(refs, existing_urls, wanted)
        for article_id, title in selected_refs:
            records.append(
                {
                    "selected_rank": len(records) + 1,
                    "seed_version": "sillok-v2-live-to-100",
                    "status": "candidate",
                    "sillok_id": article_id,
                    "source_url": f"https://sillok.history.go.kr/id/{article_id}",
                    "period": period,
                    "title": f"{period}: {title}",
                    "primary_bucket": "time_distribution",
                    "score": 0,
                    "score_parts": {},
                    "selection_reasons": ["live_candidate", "time_distribution"],
                    "evaluation_matches": [],
                    "sort_key": article_id,
                    "content_hash": None,
                    "dedupe_keys": {
                        "sillok_id": article_id,
                        "source_url": f"https://sillok.history.go.kr/id/{article_id}",
                    },
                }
            )
        period_reports[period] = {
            "status": "fetched_refs",
            "record_code": code,
            "remaining_after_legacy": shortage,
            "refs_total": len(refs),
            "wanted_candidates": wanted,
            "selected_candidates": len(selected_refs),
            "excluded_existing": len(refs)
            - len([ref for ref in refs if f"https://sillok.history.go.kr/id/{ref[0]}" not in existing_urls]),
        }
        time.sleep(args.delay)

    manifest = {
        "schema_version": "sillok-live-candidate-manifest-v1",
        "seed_version": "sillok-v2-live-to-100",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "sillok_list_pages" if args.fetch_refs else "shortage_plan_only",
        "live_fetch": bool(args.fetch_refs),
        "detail_fetch": False,
        "target_per_period": args.target_per_period,
        "candidate_multiplier": args.candidate_multiplier,
        "record_count": len(records),
        "quality": {
            "duplicates": find_duplicates(records),
            "period_counts": dict(Counter(record["period"] for record in records)),
        },
        "periods": period_reports,
        "records": records,
    }
    output = Path(args.output)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"periods={len(shortages)} candidates={len(records)} output={output.resolve()}")


def shortage_periods(
    plan: dict[str, Any],
    limit_periods: int,
    current_counts: dict[str, int] | None = None,
    target_per_period: int | None = None,
) -> list[tuple[str, int]]:
    if current_counts is not None:
        target = target_per_period or int(plan.get("target_per_period") or 100)
        shortages = [(period, max(0, target - int(current_counts.get(period, 0)))) for period in plan["periods"]]
        shortages = [(period, shortage) for period, shortage in shortages if shortage > 0]
        shortages.sort(key=lambda item: (-item[1], item[0]))
        return shortages[:limit_periods] if limit_periods > 0 else shortages

    shortages = [
        (period, int(item["remaining_after_legacy"]))
        for period, item in plan["periods"].items()
        if int(item["remaining_after_legacy"]) > 0
    ]
    shortages.sort(key=lambda item: (-item[1], item[0]))
    return shortages[:limit_periods] if limit_periods > 0 else shortages


def load_existing_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {record.get("source_url", "") for record in payload.get("records", []) if record.get("source_url")}


def load_db_urls(db) -> set[str]:
    return {
        source_url
        for (source_url,) in db.query(RagDocument.source_url)
        .filter(RagDocument.source_url.like("https://sillok.history.go.kr/id/%"))
        .all()
        if source_url
    }


def load_db_period_counts(db) -> dict[str, int]:
    counts = Counter(
        period
        for (period,) in db.query(RagDocument.period)
        .filter(RagDocument.corpus == "sillok-v2", RagDocument.source_type == "sillok")
        .all()
        if period
    )
    return dict(counts)


def select_time_distributed_refs(
    refs: list[tuple[str, str]],
    existing_urls: set[str],
    wanted: int,
) -> list[tuple[str, str]]:
    available = [ref for ref in refs if f"https://sillok.history.go.kr/id/{ref[0]}" not in existing_urls]
    if wanted <= 0 or len(available) <= wanted:
        return available
    selected = []
    seen = set()
    for index in range(wanted):
        position = round(index * (len(available) - 1) / max(1, wanted - 1))
        ref = available[position]
        if ref[0] not in seen:
            selected.append(ref)
            seen.add(ref[0])
    if len(selected) < wanted:
        for ref in available:
            if ref[0] in seen:
                continue
            selected.append(ref)
            seen.add(ref[0])
            if len(selected) >= wanted:
                break
    return selected


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


if __name__ == "__main__":
    main()
