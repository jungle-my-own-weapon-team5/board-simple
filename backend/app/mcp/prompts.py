def summarize_post_thread(post_id: int) -> str:
    """Prompt for summarizing a board post and its comments."""
    return (
        f"Use the get_post_with_comments tool with post_id={post_id}. "
        "Summarize the post's main point, important context, open questions, "
        "and the comment discussion. Keep the summary concise and factual."
    )


def draft_comment(post_id: int, intent: str) -> str:
    """Prompt for drafting a comment for a board post."""
    return (
        f"Use the get_post_with_comments tool with post_id={post_id}. "
        f"Draft a helpful comment with this intent: {intent}. "
        "The comment should respond to the post context directly and avoid inventing facts."
    )


def improve_post_markdown(title: str, content: str) -> str:
    """Prompt for improving a Markdown board post."""
    return (
        "Improve this Markdown board post while preserving the author's meaning. "
        "Make the structure clearer, keep any tags, and do not add unsupported claims.\n\n"
        f"Title: {title}\n\n"
        f"Content:\n{content}"
    )
