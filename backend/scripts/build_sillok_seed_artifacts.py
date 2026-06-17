from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session_local
from app.models.ai import RagChunk, RagDocument
from scripts.fetch_sillok_seed import fetch_article_detail


def main() -> None:
    parser = argparse.ArgumentParser(description="Build md, metadata_json, and embedding_text artifacts for Sillok seed v2.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", default="../rag_seed/sillok-v2-demo-500")
    parser.add_argument("--limit", type=int, default=0, help="0 means all manifest records.")
    parser.add_argument("--start-rank", type=int, default=1)
    parser.add_argument("--fetch-live", action="store_true", help="Fetch missing detail pages from sillok.history.go.kr.")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between live fetches when --fetch-live is used.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    records = select_records(manifest.get("records", []), args.start_rank, args.limit)

    db = get_session_local()()
    try:
        result = build_artifacts(
            db=db,
            manifest=manifest,
            records=records,
            output_dir=output_dir,
            fetch_live=args.fetch_live,
            delay=args.delay,
            overwrite=args.overwrite,
        )
    finally:
        db.close()

    report_path = output_dir / "artifact_build_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    snapshot_path = output_dir / "manifest.json"
    snapshot_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"processed={result['processed']} written={result['written']} skipped={result['skipped']} "
        f"missing={result['missing']} failed={result['failed']} report={report_path.resolve()}"
    )


def build_artifacts(
    db: Session,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    output_dir: Path,
    fetch_live: bool,
    delay: float,
    overwrite: bool,
) -> dict[str, Any]:
    for directory in [output_dir / "documents", output_dir / "metadata_json", output_dir / "embedding_text"]:
        directory.mkdir(parents=True, exist_ok=True)

    db_sources = load_db_sources(db, [record["source_url"] for record in records])
    statuses = []
    written = skipped = missing = failed = 0
    live_fetches = 0

    for record in records:
        article_id = record["sillok_id"]
        paths = artifact_paths(output_dir, record)
        if not overwrite and all(path.exists() for path in paths.values()):
            skipped += 1
            statuses.append(status_record(record, "skipped", paths))
            continue

        try:
            source = db_sources.get(record["source_url"])
            if source is None and fetch_live:
                detail = fetch_article_detail(article_id, record.get("title", ""), include_original=False)
                source = source_from_live_detail(record, detail)
                live_fetches += 1
                if delay > 0:
                    time.sleep(delay)
            if source is None:
                missing += 1
                statuses.append(status_record(record, "missing_source", paths))
                continue

            artifact = make_artifact(manifest, record, source, paths)
            write_artifact(paths, artifact)
            written += 1
            statuses.append(status_record(record, "written", paths, artifact["content_hash"]))
        except Exception as exc:
            failed += 1
            statuses.append(status_record(record, "failed", paths, error=f"{type(exc).__name__}: {exc}"))

    return {
        "schema_version": "sillok-seed-artifact-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed_version": manifest.get("seed_version", ""),
        "manifest_record_count": manifest.get("record_count", 0),
        "processed": len(records),
        "written": written,
        "skipped": skipped,
        "missing": missing,
        "failed": failed,
        "fetch_live": fetch_live,
        "live_fetches": live_fetches,
        "output_dir": str(output_dir),
        "statuses": statuses,
    }


def select_records(records: list[dict[str, Any]], start_rank: int, limit: int) -> list[dict[str, Any]]:
    selected = [record for record in records if int(record.get("selected_rank", 0)) >= start_rank]
    return selected if limit <= 0 else selected[:limit]


def load_db_sources(db: Session, source_urls: list[str]) -> dict[str, dict[str, Any]]:
    if not source_urls:
        return {}
    documents = db.scalars(select(RagDocument).where(RagDocument.source_url.in_(source_urls))).all()
    if not documents:
        return {}
    chunks = db.scalars(
        select(RagChunk)
        .where(RagChunk.document_id.in_([document.id for document in documents]))
        .order_by(RagChunk.document_id, RagChunk.chunk_index)
    ).all()
    chunks_by_document: dict[int, list[RagChunk]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

    sources = {}
    for document in documents:
        raw_content = normalize_text("\n\n".join(chunk.content for chunk in chunks_by_document.get(document.id, [])))
        inline_metadata = extract_inline_metadata(raw_content)
        metadata = {**parse_json_object(document.metadata_json), **inline_metadata}
        sources[document.source_url] = {
            "source_material": "current_db",
            "title": document.title,
            "period": document.period,
            "source_url": document.source_url,
            "source_type": document.source_type,
            "corpus": document.corpus,
            "metadata": metadata,
            "content": strip_seed_boilerplate(raw_content),
        }
    return sources


def source_from_live_detail(record: dict[str, Any], detail: dict[str, str]) -> dict[str, Any]:
    return {
        "source_material": "live_sillok",
        "title": f"{record.get('period', '')}: {detail['title']}".strip(": "),
        "period": record.get("period", ""),
        "source_url": detail["url"],
        "source_type": "sillok",
        "corpus": "sillok-v2",
        "metadata": {
            "sillok_id": record["sillok_id"],
            "date": detail["date"],
            "categories": detail["categories"],
        },
        "content": normalize_text(detail["translation"]),
    }


def make_artifact(
    manifest: dict[str, Any],
    record: dict[str, Any],
    source: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    content = normalize_text(source["content"])
    content_hash = sha256_text(content)
    metadata = make_metadata(manifest, record, source, content, content_hash, paths)
    embedding_text = make_embedding_text(record, source, content, metadata)
    markdown = make_markdown(record, source, content, metadata)
    return {
        "markdown": markdown,
        "metadata": metadata,
        "embedding_text": embedding_text,
        "content_hash": content_hash,
    }


def make_metadata(
    manifest: dict[str, Any],
    record: dict[str, Any],
    source: dict[str, Any],
    content: str,
    content_hash: str,
    paths: dict[str, Path],
) -> dict[str, Any]:
    source_metadata = source.get("metadata", {})
    categories = source_metadata.get("categories") or source_metadata.get("category") or ""
    return {
        "schema_version": "sillok-seed-artifact-v1",
        "seed_version": manifest.get("seed_version", record.get("seed_version", "")),
        "status": "cleaned",
        "selected_rank": record.get("selected_rank"),
        "sillok_id": record["sillok_id"],
        "source_url": record["source_url"],
        "period": record.get("period", ""),
        "title": record.get("title", source.get("title", "")),
        "date": source_metadata.get("date", ""),
        **parse_date_metadata(record["sillok_id"], source_metadata.get("date", "")),
        "categories": split_categories(categories),
        "primary_bucket": record.get("primary_bucket", ""),
        "score": record.get("score", 0),
        "score_parts": record.get("score_parts", {}),
        "selection_reasons": record.get("selection_reasons", []),
        "evaluation_matches": record.get("evaluation_matches", []),
        "source_material": source.get("source_material", ""),
        "source_warning": source_warning(record["sillok_id"]),
        "source_type": source.get("source_type", ""),
        "corpus": "sillok-v2",
        "content_hash": content_hash,
        "content_length": len(content),
        "artifact_paths": {key: str(path) for key, path in paths.items()},
        "diagnostic_tag_policy": manifest.get("diagnostic_tag_policy", ""),
    }


def make_embedding_text(
    record: dict[str, Any],
    source: dict[str, Any],
    content: str,
    metadata: dict[str, Any],
) -> str:
    categories = ", ".join(metadata["categories"]) or "분류 정보 없음"
    summary = focused_summary(content)
    lines = [
        f"이 문서는 {metadata['period']}의 조선왕조실록 기사이다.",
        f"기사 제목은 {metadata['title']}이다.",
        f"기사 ID는 {metadata['sillok_id']}이고 출처 URL은 {metadata['source_url']}이다.",
        f"선별 주제 범주는 {metadata['primary_bucket']}이며 분류는 {categories}이다.",
    ]
    if metadata.get("date"):
        lines.append(f"실록 날짜 정보는 {metadata['date']}이다.")
    if record.get("selection_reasons"):
        lines.append(f"선별 근거는 {', '.join(record['selection_reasons'])}이다.")
    if record.get("evaluation_matches"):
        lines.append(f"평가용 진단 태그는 {', '.join(record['evaluation_matches'])}이다.")
    lines.append(f"핵심 내용: {summary}")
    return "\n".join(lines).strip() + "\n"


def make_markdown(record: dict[str, Any], source: dict[str, Any], content: str, metadata: dict[str, Any]) -> str:
    frontmatter = {
        "title": metadata["title"],
        "period": metadata["period"],
        "source_url": metadata["source_url"],
        "sillok_id": metadata["sillok_id"],
        "seed_version": metadata["seed_version"],
        "content_hash": metadata["content_hash"],
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f'{key}: "{escape_frontmatter(str(value))}"')
    lines.extend(["---", "", f"# {metadata['title']}", ""])
    lines.append(f"- 기사 ID: {metadata['sillok_id']}")
    lines.append(f"- URL: {metadata['source_url']}")
    if metadata.get("date"):
        lines.append(f"- 날짜: {metadata['date']}")
    if metadata["categories"]:
        lines.append(f"- 분류: {', '.join(metadata['categories'])}")
    lines.extend(["", "## 국역", "", content, ""])
    return "\n".join(lines).strip() + "\n"


def write_artifact(paths: dict[str, Path], artifact: dict[str, Any]) -> None:
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    paths["md"].write_text(artifact["markdown"], encoding="utf-8")
    paths["metadata_json"].write_text(json.dumps(artifact["metadata"], ensure_ascii=False, indent=2), encoding="utf-8")
    paths["embedding_text"].write_text(artifact["embedding_text"], encoding="utf-8")


def artifact_paths(output_dir: Path, record: dict[str, Any]) -> dict[str, Path]:
    period = slug(record.get("period", "unknown"))
    stem = f"{int(record.get('selected_rank', 0)):04d}-{record['sillok_id']}"
    return {
        "md": output_dir / "documents" / period / f"{stem}.md",
        "metadata_json": output_dir / "metadata_json" / period / f"{stem}.json",
        "embedding_text": output_dir / "embedding_text" / period / f"{stem}.txt",
    }


def status_record(
    record: dict[str, Any],
    status: str,
    paths: dict[str, Path],
    content_hash: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "selected_rank": record.get("selected_rank"),
        "sillok_id": record.get("sillok_id"),
        "source_url": record.get("source_url"),
        "status": status,
        "content_hash": content_hash,
        "artifact_paths": {key: str(path) for key, path in paths.items()},
    }
    if error:
        payload["error"] = error
    return payload


def parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def split_categories(categories: Any) -> list[str]:
    if isinstance(categories, list):
        return [str(item).strip() for item in categories if str(item).strip()]
    return [item.strip() for item in str(categories or "").split("/") if item.strip()]


def extract_inline_metadata(content: str) -> dict[str, str]:
    metadata = {}
    for line in content.splitlines()[:12]:
        stripped = line.strip()
        if stripped.startswith("- 출전:"):
            metadata["date"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("- 분류:"):
            metadata["categories"] = stripped.split(":", 1)[1].strip()
    return metadata


def strip_seed_boilerplate(content: str) -> str:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- 출전:", "- 기사 ID:", "- URL:", "- 분류:")):
            continue
        if stripped in {"## 국역", "## 원문"}:
            if stripped == "## 원문":
                break
            continue
        if is_classical_original_block_start(stripped):
            break
        lines.append(line)
    return normalize_text("\n".join(lines))


def is_classical_original_block_start(line: str) -> bool:
    if not line:
        return False
    hangul_count = len(re.findall(r"[가-힣]", line))
    cjk_count = len(re.findall(r"[一-龥]", line))
    if hangul_count > 0 or cjk_count < 3:
        return False
    return line.startswith("○") or bool(re.match(r"^[一-龥]", line))


def parse_date_metadata(article_id: str, date: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "record_code": article_id[:3],
        "volume": None,
        "king_year": None,
        "month": None,
        "day": None,
        "article_no": None,
    }
    match = re.search(
        r"(?P<volume>\d+)권,.*?\s+(?P<year>\d+)년\s+(?P<month>\d+)월\s+(?P<day>\d+)일.*?(?P<article_no>\d+)/\d+\s+기사",
        date or "",
    )
    if not match:
        return metadata
    metadata.update(
        {
            "volume": int(match.group("volume")),
            "king_year": int(match.group("year")),
            "month": int(match.group("month")),
            "day": int(match.group("day")),
            "article_no": int(match.group("article_no")),
        }
    )
    return metadata


def source_warning(article_id: str) -> str | None:
    if article_id.startswith(("kza", "kzb", "kzc")):
        return "고종·순종 계열 자료는 편찬 경위상 인용 주의"
    return None


def focused_summary(content: str, limit: int = 650) -> str:
    compact = normalize_text(re.sub(r"^#.*?$", "", content, flags=re.M))
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def normalize_text(text: str) -> str:
    text = (text or "").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", value or "unknown").strip("-")
    return cleaned or "unknown"


def escape_frontmatter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


if __name__ == "__main__":
    main()
