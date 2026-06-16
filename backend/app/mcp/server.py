from mcp.server.fastmcp import FastMCP

from app.mcp.prompts import draft_comment, improve_post_markdown, summarize_post_thread
from app.mcp.tools import (
    create_post,
    get_comments,
    get_post,
    get_post_with_comments,
    get_recent_posts,
    list_tags,
    search_posts,
)


def create_board_mcp() -> FastMCP:
    board_mcp = FastMCP(
        "Board Simple",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    board_mcp.tool()(search_posts)
    board_mcp.tool()(get_post)
    board_mcp.tool()(get_comments)
    board_mcp.tool()(get_post_with_comments)
    board_mcp.tool()(list_tags)
    board_mcp.tool()(get_recent_posts)
    board_mcp.tool()(create_post)

    board_mcp.prompt()(summarize_post_thread)
    board_mcp.prompt()(draft_comment)
    board_mcp.prompt()(improve_post_markdown)

    return board_mcp
