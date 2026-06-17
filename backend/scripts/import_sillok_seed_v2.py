from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session_local
from app.models.ai import RagChunk, RagDocument


CORPUS = "sillok-v2"
SOURCE_TYPE = "sillok"


@dataclass
class SeedArtifact:
    sillok_id: str
    source_url: str
    title: str
    period: str
    metadata_json: str
    embedding_text: str
    document_markdown: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Sillok v2 seed artifacts into rag_documents/rag_chunks.")
    parser.add_argument("--seed-dir", default="rag_seed/sillok-v2-demo-500")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    seed_dir = Path(args.seed_dir)
    artifacts = load_artifacts(seed_dir)
    if args.limit > 0:
        artifacts = artifacts[: args.limit]

    db = get_session_local()()
    try:
        result = import_artifacts(db, artifacts, apply=args.apply)
    finally:
        db.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))


def load_artifacts(seed_dir: Path) -> list[SeedArtifact]:
    metadata_paths = sorted((seed_dir / "metadata_json").rglob("*.json"))
    artifacts = []
    errors = []
    for metadata_path in metadata_paths:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            relative = metadata_path.relative_to(seed_dir / "metadata_json")
            embedding_path = seed_dir / "embedding_text" / relative.with_suffix(".txt")
            document_path = seed_dir / "documents" / relative.with_suffix(".md")
            if not embedding_path.exists():
                raise FileNotFoundError(f"missing embedding_text: {embedding_path}")
            if not document_path.exists():
                raise FileNotFoundError(f"missing document: {document_path}")
            artifacts.append(
                SeedArtifact(
                    sillok_id=required_str(metadata, "sillok_id"),
                    source_url=required_str(metadata, "source_url"),
                    title=required_str(metadata, "title"),
                    period=required_str(metadata, "period"),
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                    embedding_text=embedding_path.read_text(encoding="utf-8").strip(),
                    document_markdown=document_path.read_text(encoding="utf-8"),
                )
            )
        except Exception as exc:
            errors.append({"path": str(metadata_path), "error": f"{type(exc).__name__}: {exc}"})
    if errors:
        raise SystemExit(json.dumps({"artifact_errors": errors[:20], "error_count": len(errors)}, ensure_ascii=False, indent=2))
    return artifacts


def import_artifacts(db: Session, artifacts: list[SeedArtifact], apply: bool) -> dict[str, Any]:
    duplicate_ids = duplicated_values(artifact.sillok_id for artifact in artifacts)
    duplicate_urls = duplicated_values(artifact.source_url for artifact in artifacts)
    if duplicate_ids or duplicate_urls:
        return {
            "status": "error",
            "reason": "duplicates_in_artifacts",
            "duplicate_sillok_ids": sorted(duplicate_ids),
            "duplicate_source_urls": sorted(duplicate_urls),
        }

    existing = load_existing_documents(db, artifacts)
    to_create = 0
    to_update = 0
    unchanged = 0
    chunk_rewrites = 0

    for artifact in artifacts:
        document = existing.get(artifact.source_url)
        if document is None:
            to_create += 1
            if apply:
                document = RagDocument(
                    title=artifact.title,
                    period=artifact.period,
                    source_url=artifact.source_url,
                    source_type=SOURCE_TYPE,
                    corpus=CORPUS,
                    metadata_json=artifact.metadata_json,
                )
                db.add(document)
                db.flush()
                db.add(RagChunk(document_id=document.id, chunk_index=0, content=artifact.embedding_text))
        else:
            current_chunk = first_chunk(db, document)
            metadata_changed = (
                document.title != artifact.title
                or document.period != artifact.period
                or document.source_type != SOURCE_TYPE
                or document.corpus != CORPUS
                or document.metadata_json != artifact.metadata_json
            )
            chunk_changed = current_chunk is None or current_chunk.content != artifact.embedding_text
            if metadata_changed or chunk_changed:
                to_update += 1
            else:
                unchanged += 1
            if apply and (metadata_changed or chunk_changed):
                document.title = artifact.title
                document.period = artifact.period
                document.source_type = SOURCE_TYPE
                document.corpus = CORPUS
                document.metadata_json = artifact.metadata_json
                if chunk_changed:
                    rewrite_chunks(db, document, artifact.embedding_text)
                    chunk_rewrites += 1

    if apply:
        db.commit()

    return {
        "status": "applied" if apply else "dry_run",
        "artifact_count": len(artifacts),
        "to_create": to_create,
        "to_update": to_update,
        "unchanged": unchanged,
        "chunk_rewrites": chunk_rewrites if apply else None,
        "corpus": CORPUS,
        "source_type": SOURCE_TYPE,
    }


def load_existing_documents(db: Session, artifacts: list[SeedArtifact]) -> dict[str, RagDocument]:
    urls = [artifact.source_url for artifact in artifacts]
    if not urls:
        return {}
    documents = db.scalars(
        select(RagDocument)
        .where(RagDocument.corpus == CORPUS)
        .where(RagDocument.source_url.in_(urls))
    ).all()
    return {document.source_url: document for document in documents}


def first_chunk(db: Session, document: RagDocument) -> RagChunk | None:
    return db.scalar(
        select(RagChunk)
        .where(RagChunk.document_id == document.id)
        .order_by(RagChunk.chunk_index)
        .limit(1)
    )


def rewrite_chunks(db: Session, document: RagDocument, content: str) -> None:
    chunks = db.scalars(select(RagChunk).where(RagChunk.document_id == document.id)).all()
    for chunk in chunks:
        db.delete(chunk)
    db.flush()
    db.add(RagChunk(document_id=document.id, chunk_index=0, content=content))


def required_str(metadata: dict[str, Any], key: str) -> str:
    value = str(metadata.get(key) or "").strip()
    if not value:
        raise ValueError(f"metadata missing required key: {key}")
    return value


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
