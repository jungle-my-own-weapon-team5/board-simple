import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.post import Post
from app.services.rag import get_rag_service

logger = logging.getLogger(__name__)


@dataclass
class DuplicateMatchResult:
    post_id: int
    title: str
    reason: str
    score: float | None = None


class DuplicateCheckService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def check(
        self,
        db: Session,
        title: str,
        url: str | None = None,
        content: str | None = None,
        limit: int = 5,
    ) -> list[DuplicateMatchResult]:
        seen: set[int] = set()
        matches: list[DuplicateMatchResult] = []

        self._append_url_matches(db, matches, seen, url)
        self._append_title_matches(db, matches, seen, title)
        self._append_rag_matches(db, matches, seen, title, content)
        return matches[:limit]

    def _append_url_matches(
        self,
        db: Session,
        matches: list[DuplicateMatchResult],
        seen: set[int],
        url: str | None,
    ) -> None:
        normalized = normalize_url(url)
        if normalized is None:
            return
        posts = db.scalars(
            select(Post).where(Post.source_url.is_not(None)).order_by(Post.created_at.desc())
        ).all()
        for post in posts:
            if post.id in seen or normalize_url(post.source_url) != normalized:
                continue
            seen.add(post.id)
            matches.append(DuplicateMatchResult(post.id, post.title, "same_url"))

    def _append_title_matches(
        self,
        db: Session,
        matches: list[DuplicateMatchResult],
        seen: set[int],
        title: str,
    ) -> None:
        needle = " ".join(title.split()).lower()
        if not needle:
            return
        posts = db.scalars(select(Post).order_by(Post.created_at.desc()).limit(100)).all()
        for post in posts:
            if post.id in seen:
                continue
            score = SequenceMatcher(None, needle, " ".join(post.title.split()).lower()).ratio()
            if score < 0.86:
                continue
            seen.add(post.id)
            matches.append(DuplicateMatchResult(post.id, post.title, "similar_title", score))

    def _append_rag_matches(
        self,
        db: Session,
        matches: list[DuplicateMatchResult],
        seen: set[int],
        title: str,
        content: str | None,
    ) -> None:
        rag_service = get_rag_service()
        if not rag_service.is_configured():
            return
        query = f"Title: {title}\n\n{content or ''}".strip()
        try:
            results = rag_service._get_vector_store().similarity_search_with_score(query, k=8)
        except Exception:
            logger.exception("Failed to search duplicates with RAG")
            return

        post_ids: list[int] = []
        by_id: dict[int, tuple[str, float | None]] = {}
        for document, score in results:
            if score is None:
                continue
            try:
                rag_score = float(score)
            except (TypeError, ValueError):
                continue
            if rag_score > self.settings.rag_duplicate_score_threshold:
                continue
            metadata = getattr(document, "metadata", {})
            if not isinstance(metadata, dict) or "post_id" not in metadata:
                continue
            try:
                post_id = int(metadata["post_id"])
            except (TypeError, ValueError):
                continue
            if post_id in seen or post_id in by_id:
                continue
            post_ids.append(post_id)
            by_id[post_id] = (
                str(metadata.get("title") or "").strip(),
                rag_score,
            )

        if not post_ids:
            return
        titles_by_id = dict(db.execute(select(Post.id, Post.title).where(Post.id.in_(post_ids))).all())
        for post_id in post_ids:
            if post_id in seen or post_id not in titles_by_id:
                continue
            metadata_title, score = by_id[post_id]
            seen.add(post_id)
            matches.append(
                DuplicateMatchResult(
                    post_id=post_id,
                    title=metadata_title or titles_by_id[post_id],
                    reason="rag",
                    score=score,
                )
            )


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip().rstrip("/") or None
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


_duplicate_check_service: DuplicateCheckService | None = None


def get_duplicate_check_service() -> DuplicateCheckService:
    global _duplicate_check_service
    if _duplicate_check_service is None:
        _duplicate_check_service = DuplicateCheckService()
    return _duplicate_check_service
