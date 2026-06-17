import re

from openai import OpenAI, OpenAIError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.post import Post
from app.models.user import User
from app.repositories import posts as post_repository
from app.schemas.post import (
    PostCreate,
    PostDuplicateCandidate,
    PostThumbnailRequest,
    PostThumbnailResponse,
    PostUpdate,
)
from app.services import rag as rag_service
from app.services.errors import NotFoundError, PermissionDeniedError
from app.services.tags import TAG_NAME_PATTERN, get_or_create_tags, normalize_tag_names

TERM_PATTERN = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
DUPLICATE_TERM_LIMIT = 8
DUPLICATE_CANDIDATE_LIMIT = 8


class ThumbnailNotConfiguredError(Exception):
    pass


class ThumbnailGenerationError(Exception):
    pass


def _get_post_or_raise(db: Session, post_id: int) -> Post:
    post = post_repository.get_post(db, post_id)
    if post is None:
        raise NotFoundError("Post not found")
    return post


def _clean_query(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_tag(value: str | None) -> str | None:
    cleaned = _clean_query(value)
    if cleaned is None:
        return None
    tags = normalize_tag_names([cleaned])
    if not tags or not re.fullmatch(TAG_NAME_PATTERN, tags[0]):
        return None
    return tags[0]


def list_posts(
    db: Session,
    *,
    page: int,
    size: int,
    q: str | None,
    content_q: str | None = None,
    tag: str | None = None,
) -> tuple[list[Post], int]:
    q = _clean_query(q)
    content_q = _clean_query(content_q)
    tag = _clean_tag(tag)
    return (
        post_repository.list_posts(db, page=page, size=size, q=q, content_q=content_q, tag=tag),
        post_repository.count_posts(db, q=q, content_q=content_q, tag=tag),
    )


def get_post(db: Session, post_id: int) -> Post:
    return _get_post_or_raise(db, post_id)


def _terms(text: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in TERM_PATTERN.findall(text.lower()):
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= DUPLICATE_TERM_LIMIT:
            break
    return terms


def _snippet(content: str, limit: int = 180) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _duplicate_reasons(post: Post, *, title_terms: list[str], content_terms: list[str], tags: list[str]) -> list[str]:
    reasons: list[str] = []
    title = post.title.lower()
    content = post.content.lower()
    if any(term in title for term in title_terms):
        reasons.append("제목이 비슷합니다")
    if any(term in content for term in content_terms):
        reasons.append("본문에 비슷한 표현이 있습니다")

    tag_overlap = sorted({tag.name for tag in post.tags}.intersection(tags))
    if tag_overlap:
        reasons.append("태그가 겹칩니다: " + ", ".join(f"#{tag}" for tag in tag_overlap))
    return reasons


def check_duplicate_posts(
    db: Session,
    *,
    title: str,
    content: str,
    tags: list[str],
    exclude_post_id: int | None = None,
) -> list[PostDuplicateCandidate]:
    title_terms = _terms(title)
    content_terms = _terms(content)
    normalized_tags = normalize_tag_names(tags)
    posts = post_repository.list_duplicate_candidates(
        db,
        title_terms=title_terms,
        content_terms=content_terms,
        tags=normalized_tags,
        exclude_post_id=exclude_post_id,
        limit=DUPLICATE_CANDIDATE_LIMIT,
    )

    candidates = [
        PostDuplicateCandidate(
            id=post.id,
            title=post.title,
            author=post.author,
            tags=post.tags,
            created_at=post.created_at,
            updated_at=post.updated_at,
            reasons=_duplicate_reasons(
                post,
                title_terms=title_terms,
                content_terms=content_terms,
                tags=normalized_tags,
            ),
            snippet=_snippet(post.content),
        )
        for post in posts
    ]
    return sorted(candidates, key=lambda candidate: (-len(candidate.reasons), -candidate.id))


def _get_openai_client(settings: Settings) -> OpenAI:
    if not settings.openai_api_key:
        raise ThumbnailNotConfiguredError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=settings.openai_api_key)


def _thumbnail_prompt(payload: PostThumbnailRequest) -> str:
    tag_text = ", ".join(f"#{tag}" for tag in payload.tags) or "none"
    content = " ".join(payload.content.split())
    if len(content) > 1200:
        content = f"{content[:1197]}..."
    return (
        "Create a clean editorial thumbnail image for a technical board post. "
        "Do not include readable text, logos, watermarks, or UI chrome. "
        "Use a modern, high-contrast composition that visually summarizes the post.\n\n"
        f"Title: {payload.title}\n"
        f"Tags: {tag_text}\n"
        f"Post content summary source:\n{content}"
    )


def generate_thumbnail_markdown(payload: PostThumbnailRequest) -> PostThumbnailResponse:
    settings = get_settings()
    client = _get_openai_client(settings)
    try:
        result = client.images.generate(
            model=settings.openai_image_model,
            prompt=_thumbnail_prompt(payload),
            size="1536x1024",
            quality="low",
            output_format="png",
        )
    except OpenAIError as exc:
        raise ThumbnailGenerationError("Failed to generate thumbnail image") from exc

    image_base64 = result.data[0].b64_json if result.data else None
    if not image_base64:
        raise ThumbnailGenerationError("Image generation response did not include image data")

    image_data_url = f"data:image/png;base64,{image_base64}"
    return PostThumbnailResponse(
        image_markdown=f"![thumbnail]({image_data_url})",
        image_data_url=image_data_url,
    )


def create_post(db: Session, payload: PostCreate, current_user: User) -> Post:
    tags = get_or_create_tags(db, payload.tags)
    post = post_repository.create_post(
        db,
        title=payload.title,
        content=payload.content,
        author_id=current_user.id,
        tags=tags,
    )
    post_id = post.id
    db.commit()

    # 게시글과 태그 관계를 먼저 확정한 뒤 다시 조회해서 RAG 색인에 사용합니다.
    post = _get_post_or_raise(db, post_id)
    rag_service.index_post_chunks(db, post)
    db.commit()
    return _get_post_or_raise(db, post_id)


def update_post(
    db: Session,
    post_id: int,
    payload: PostUpdate,
    current_user: User,
) -> Post:
    post = _get_post_or_raise(db, post_id)
    if post.author_id != current_user.id:
        raise PermissionDeniedError("Only the author can update this post")

    tags = get_or_create_tags(db, payload.tags)
    post_repository.update_post(
        post,
        title=payload.title,
        content=payload.content,
        tags=tags,
    )
    db.commit()

    # 수정된 제목, 본문, 태그를 기준으로 기존 RAG 청크를 새 상태로 맞춥니다.
    post = _get_post_or_raise(db, post_id)
    rag_service.index_post_chunks(db, post)
    db.commit()
    return _get_post_or_raise(db, post_id)


def delete_post(db: Session, post_id: int, current_user: User) -> None:
    post = _get_post_or_raise(db, post_id)
    if post.author_id != current_user.id:
        raise PermissionDeniedError("Only the author can delete this post")

    post_repository.delete_post(db, post)
    db.commit()
