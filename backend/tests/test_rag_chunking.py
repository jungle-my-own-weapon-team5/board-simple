from app.rag.chunking import MAX_CHUNK_CHARS, chunk_markdown, prepare_post_chunks


def test_chunk_markdown_without_headings_uses_whole_post() -> None:
    chunks = chunk_markdown("plain body\n\nsecond paragraph")

    assert len(chunks) == 1
    assert chunks[0].heading_path is None
    assert chunks[0].anchor is None
    assert chunks[0].content == "plain body\n\nsecond paragraph"


def test_chunk_markdown_uses_heading_sections_and_unique_anchors() -> None:
    chunks = chunk_markdown("# Intro\nA\n\n## Usage\nB\n\n## Usage\nC")

    assert [chunk.heading_path for chunk in chunks] == [
        "Intro",
        "Intro > Usage",
        "Intro > Usage",
    ]
    assert [chunk.anchor for chunk in chunks] == [
        "user-content-intro",
        "user-content-usage",
        "user-content-usage-2",
    ]


def test_chunk_markdown_ignores_headings_inside_fenced_code() -> None:
    chunks = chunk_markdown("```\n# Not a heading\n```\n\n# Real heading\nBody")

    assert len(chunks) == 2
    assert chunks[0].heading_path is None
    assert chunks[1].heading_path == "Real heading"
    assert chunks[1].anchor == "user-content-real-heading"


def test_chunk_markdown_splits_long_sections() -> None:
    content = "# Big\n\n" + "\n\n".join(f"paragraph {index} " + ("x" * 300) for index in range(10))

    chunks = chunk_markdown(content)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert all(chunk.heading_path == "Big" for chunk in chunks)


def test_prepare_post_chunks_hash_changes_when_embedding_text_changes() -> None:
    first = prepare_post_chunks("Title", ["python"], "# Intro\nBody")[0]
    changed_content = prepare_post_chunks("Title", ["python"], "# Intro\nChanged")[0]
    changed_tags = prepare_post_chunks("Title", ["fastapi"], "# Intro\nBody")[0]

    assert first.content_hash != changed_content.content_hash
    assert first.content_hash != changed_tags.content_hash
    assert "Tags: #python" in first.embedding_text
    assert "Heading: Intro" in first.embedding_text


def test_prepare_post_chunks_keeps_embedding_text_under_max_chars() -> None:
    title = "T" * 200
    tags = [f"tag{index}" for index in range(30)]
    heading = "H" * 500
    content = f"# {heading}\n\n" + "\n\n".join("x" * 300 for _ in range(10))

    chunks = prepare_post_chunks(title, tags, content)

    assert len(chunks) > 1
    assert all(len(chunk.embedding_text) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert all(chunk.heading_path == heading for chunk in chunks)
