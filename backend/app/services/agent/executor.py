from typing import Any

from app.mcp.tools import (
    get_comments,
    get_post,
    get_post_with_comments,
    get_recent_posts,
    list_tags,
    search_posts,
)
from app.services.agent.models import AgentActionPlan


def execute_action(plan: AgentActionPlan) -> Any:
    args = plan.args
    if plan.action == "search_posts":
        return search_posts(
            q=args.get("q"),
            page=int(args.get("page", 1)),
            size=int(args.get("size", 10)),
        )
    if plan.action == "get_recent_posts":
        return get_recent_posts(limit=int(args.get("limit", 10)))
    if plan.action == "get_post":
        return get_post(post_id=int(args["post_id"]))
    if plan.action == "get_comments":
        return get_comments(
            post_id=int(args["post_id"]),
            offset=int(args.get("offset", 0)),
            limit=int(args.get("limit", 10)),
        )
    if plan.action == "get_post_with_comments":
        return get_post_with_comments(
            post_id=int(args["post_id"]),
            comment_limit=int(args.get("comment_limit", 20)),
        )
    if plan.action == "list_tags":
        return list_tags()
    raise ValueError(f"Unsupported action: {plan.action}")
