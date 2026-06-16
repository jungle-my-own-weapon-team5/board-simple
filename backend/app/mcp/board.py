import logging

from app.core.database import get_session_local
from app.schemas.news import NewsSource
from app.services.duplicate_check import get_duplicate_check_service
from app.services.hacker_news import get_hacker_news_service
from app.services.news_curation import get_news_curation_service

logger = logging.getLogger(__name__)


def preview_web_article_tool(url: str, article_text: str | None = None) -> dict:
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        duplicate_service = get_duplicate_check_service()
        matches = duplicate_service.check(
            db,
            title=url.rsplit("/", 1)[-1] or url,
            url=url,
            content=article_text,
        )
        item = get_news_curation_service().preview_web_article(url, matches, article_text)
        if item.summary_status == "success":
            item.duplicate_matches = duplicate_service.check(
                db,
                title=item.title,
                url=item.url,
                content=item.summary,
            )
        return _candidate_dict(item)


def check_news_duplicates_tool(
    title: str,
    url: str | None = None,
    content: str | None = None,
) -> list[dict]:
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        matches = get_duplicate_check_service().check(db, title=title, url=url, content=content)
        return [_match_dict(match) for match in matches]


def preview_hacker_news_tool(
    source: NewsSource,
    query: str | None = None,
    limit: int = 10,
) -> list[dict]:
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        service = get_hacker_news_service()
        duplicate_service = get_duplicate_check_service()
        candidates = service.preview(db, source, query, limit)
        items = []
        for candidate in candidates:
            data = candidate.__dict__.copy()
            data["duplicate_matches"] = [
                _match_dict(match)
                for match in duplicate_service.check(
                    db,
                    title=candidate.title,
                    url=candidate.url,
                    content=candidate.summary,
                )
            ]
            items.append(data)
        return items


def create_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("board-simple")
    mcp.tool()(preview_web_article_tool)
    mcp.tool()(check_news_duplicates_tool)
    mcp.tool()(preview_hacker_news_tool)
    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    create_server().run(transport="stdio")


def _candidate_dict(item) -> dict:
    data = item.__dict__.copy()
    data["duplicate_matches"] = [_match_dict(match) for match in item.duplicate_matches]
    return data


def _match_dict(match) -> dict:
    return {
        "post_id": match.post_id,
        "title": match.title,
        "reason": match.reason,
        "score": match.score,
    }


if __name__ == "__main__":
    main()
