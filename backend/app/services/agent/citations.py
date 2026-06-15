"""검색 결과를 backend 검증 가능한 citation으로 변환합니다."""

from __future__ import annotations


def build_chunk_citations(search_items: list[dict[str, object]]) -> list[dict[str, object]]:
    citations: list[dict[str, object]] = []
    for item in search_items:
        chunk_id = item.get("chunk_id")
        if not isinstance(chunk_id, int):
            continue
        citations.append(
            {
                "chunk_id": chunk_id,
                "title": item.get("title"),
                "source_url": item.get("source_url"),
                "heading": item.get("heading"),
                "rank": item.get("rank"),
            }
        )
    return citations

