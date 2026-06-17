import logging

from sqlalchemy.orm import Session

from app.core.database import get_session_local
from app.schemas.news import NewsDuplicateJudgementItem, NewsSource
from app.services.duplicate_check import DuplicateMatchResult
from app.services.duplicate_check import get_duplicate_check_service
from app.services.duplicate_judgement import get_duplicate_judgement_service
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
        data = _candidate_dict(item)
        data["duplicate_judgements"] = _judgements_for_candidate(
            db,
            client_id=f"web-{item.source_id}",
            title=item.title,
            url=item.url,
            summary=item.summary,
            key_points=item.key_points,
            duplicate_matches=item.duplicate_matches,
        )
        return data


def check_news_duplicates_tool(
    title: str,
    url: str | None = None,
    content: str | None = None,
) -> list[dict]:
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        matches = get_duplicate_check_service().check(db, title=title, url=url, content=content)
        return [_match_dict(match) for match in matches]


def judge_news_duplicates_tool(items: list[dict]) -> dict:
    payload_items = [NewsDuplicateJudgementItem.model_validate(item) for item in items]
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        results = get_duplicate_judgement_service().judge(db, payload_items)
        return {"items": [item.model_dump() for item in results]}


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
            matches = duplicate_service.check(
                db,
                title=candidate.title,
                url=candidate.url,
                content=candidate.summary,
            )
            data["duplicate_matches"] = [_match_dict(match) for match in matches]
            data["duplicate_judgements"] = _judgements_for_candidate(
                db,
                client_id=f"hn-{candidate.hn_id}",
                title=candidate.title,
                url=candidate.url,
                summary=candidate.summary,
                key_points=candidate.key_points,
                duplicate_matches=matches,
            )
            items.append(data)
        return items


def create_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("board-simple")
    mcp.tool()(preview_web_article_tool)
    mcp.tool()(check_news_duplicates_tool)
    mcp.tool()(judge_news_duplicates_tool)
    mcp.tool()(preview_hacker_news_tool)
    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    create_server().run(transport="stdio")


def _candidate_dict(item) -> dict:
    data = item.__dict__.copy()
    data["duplicate_matches"] = [_match_dict(match) for match in item.duplicate_matches]
    return data


def _judgements_for_candidate(
    db: Session,
    client_id: str,
    title: str,
    url: str | None,
    summary: str | None,
    key_points: list[str],
    duplicate_matches: list[DuplicateMatchResult],
) -> list[dict]:
    if not duplicate_matches:
        return []
    item = NewsDuplicateJudgementItem(
        client_id=client_id,
        title=title,
        url=url,
        summary=summary,
        key_points=key_points,
        duplicate_matches=[_match_dict(match) for match in duplicate_matches],
    )
    response_items = get_duplicate_judgement_service().judge(db, [item])
    if not response_items:
        return []
    return [result.model_dump() for result in response_items[0].results]


def _match_dict(match) -> dict:
    return {
        "post_id": match.post_id,
        "title": match.title,
        "reason": match.reason,
        "score": match.score,
    }


if __name__ == "__main__":
    main()
