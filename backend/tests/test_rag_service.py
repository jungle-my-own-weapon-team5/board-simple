from types import SimpleNamespace

import pytest

from app.repositories.rag_chunks import RagChunkSearchRow
from app.services import rag as rag_service


def _row(
    post_id: int,
    content: str,
    *,
    cosine_distance: float = 0.3,
) -> RagChunkSearchRow:
    return RagChunkSearchRow(
        post_id=post_id,
        title=f"Post {post_id}",
        heading_path=None,
        anchor=None,
        content=content,
        cosine_distance=cosine_distance,
    )


def _patch_search_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[RagChunkSearchRow],
    *,
    top_k: int,
) -> dict[str, int]:
    captured: dict[str, int] = {}

    monkeypatch.setattr(
        rag_service,
        "get_settings",
        lambda: SimpleNamespace(openai_embedding_model="test-embedding", rag_top_k=top_k),
    )
    monkeypatch.setattr(
        rag_service.rag_chunk_repository,
        "supports_vector_search",
        lambda db: True,
    )
    monkeypatch.setattr(rag_service, "_embed_texts", lambda texts, settings: [[0.1, 0.2]])

    def fake_search_chunks_by_embedding(db, *, embedding, embedding_model, limit):
        captured["limit"] = limit
        return rows

    monkeypatch.setattr(
        rag_service.rag_chunk_repository,
        "search_chunks_by_embedding",
        fake_search_chunks_by_embedding,
    )
    return captured


def test_search_chunks_fetches_extra_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_search_dependencies(monkeypatch, [], top_k=5)

    rag_service.search_chunks(SimpleNamespace(), "FastAPI 내용 알려줘")

    assert captured["limit"] == 15


def test_search_chunks_limits_each_post_to_two_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _row(1, "post 1 chunk 1"),
        _row(1, "post 1 chunk 2"),
        _row(1, "post 1 chunk 3"),
        _row(2, "post 2 chunk 1"),
        _row(2, "post 2 chunk 2"),
        _row(2, "post 2 chunk 3"),
        _row(3, "post 3 chunk 1"),
    ]
    _patch_search_dependencies(monkeypatch, rows, top_k=5)

    chunks = rag_service.search_chunks(SimpleNamespace(), "FastAPI 내용 알려줘")

    assert [chunk.post_id for chunk in chunks] == [1, 1, 2, 2, 3]


def test_search_chunks_filters_weak_semantic_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _row(
            1,
            "strong match",
            cosine_distance=rag_service.RAG_MAX_COSINE_DISTANCE - 0.01,
        ),
        _row(
            2,
            "weak match",
            cosine_distance=rag_service.RAG_MAX_COSINE_DISTANCE + 0.01,
        ),
        _row(
            3,
            "boundary match",
            cosine_distance=rag_service.RAG_MAX_COSINE_DISTANCE,
        ),
    ]
    _patch_search_dependencies(monkeypatch, rows, top_k=5)

    chunks = rag_service.search_chunks(SimpleNamespace(), "FastAPI 내용 알려줘")

    assert [chunk.content for chunk in chunks] == ["strong match", "boundary match"]


def test_search_chunks_returns_at_most_two_when_one_post_dominates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _row(1, "post 1 chunk 1"),
        _row(1, "post 1 chunk 2"),
        _row(1, "post 1 chunk 3"),
        _row(1, "post 1 chunk 4"),
    ]
    _patch_search_dependencies(monkeypatch, rows, top_k=5)

    chunks = rag_service.search_chunks(SimpleNamespace(), "FastAPI 내용 알려줘")

    assert [chunk.content for chunk in chunks] == ["post 1 chunk 1", "post 1 chunk 2"]
