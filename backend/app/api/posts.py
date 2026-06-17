from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.post import Post
from app.models.user import User
from app.schemas.post import (
    PostCreate,
    PostListItem,
    PostPage,
    PostThumbnailCandidatesRequest,
    PostRead,
    PostThumbnailCandidatesResponse,
    PostThumbnailSelectRequest,
    PostUpdate,
)
from app.services.ai_runtime import make_post_search_summary
from app.services.mcp_server import generate_thumbnail_candidates_for_post, generate_thumbnail_for_post
from app.services.safety import post_safety_message_for
from app.services.tags import get_or_create_tags, normalize_tag_names

router = APIRouter(prefix="/posts", tags=["posts"])

UPLOAD_DIR = Path(__file__).resolve().parents[1] / "static" / "uploads"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def get_post_or_404(db: Session, post_id: int) -> Post:
    post = db.scalar(
        select(Post)
        .where(Post.id == post_id)
        .options(
            selectinload(Post.author),
            selectinload(Post.tags),
        )
    )
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.get("", response_model=PostPage)
def list_posts(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=50),
    q: str | None = Query(default=None),
    post_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    sort: str = Query(default="latest", pattern="^(latest|comments|ai)$"),
    db: Session = Depends(get_db),
) -> PostPage:
    filters = []
    if q:
        filters.append(Post.title.ilike(f"%{q}%"))
    if post_type:
        filters.append(Post.post_type == post_type)
    if category:
        filters.append(Post.category == category)
    if sort == "ai":
        filters.append(Post.ai_search_summary.is_not(None))

    total_statement = select(func.count()).select_from(Post)
    statement = select(Post).options(selectinload(Post.author), selectinload(Post.tags))
    if filters:
        total_statement = total_statement.where(*filters)
        statement = statement.where(*filters)

    total = db.scalar(total_statement) or 0
    if sort == "comments":
        statement = statement.order_by(Post.comment_count.desc(), Post.created_at.desc())
    elif sort == "ai":
        statement = statement.order_by(Post.created_at.desc())
    else:
        statement = statement.order_by(Post.created_at.desc())

    posts = db.scalars(statement.offset((page - 1) * size).limit(size)).all()
    return PostPage(
        items=[PostListItem.model_validate(post) for post in posts],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> Post:
    tag_names = normalize_tag_names(payload.tags)
    safety_message = post_safety_message_for(payload.title, payload.content, tag_names)
    if safety_message is not None:
        raise HTTPException(status_code=400, detail=safety_message)
    ai_search_summary = make_post_search_summary(
        db,
        settings,
        payload.title,
        payload.content,
        payload.post_type,
        payload.category,
        tag_names,
    )
    post = Post(
        title=payload.title,
        content=payload.content,
        post_type=payload.post_type,
        category=payload.category,
        ai_search_summary=ai_search_summary,
        thumbnail_url=payload.thumbnail_url,
        author_id=current_user.id,
    )
    post.tags = get_or_create_tags(db, tag_names)
    db.add(post)
    db.commit()
    db.refresh(post)
    return get_post_or_404(db, post.id)


@router.post("/uploads/images")
async def upload_post_image(
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="JPEG, PNG, WebP, GIF 이미지만 업로드할 수 있습니다.")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 이미지 파일은 업로드할 수 없습니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="이미지는 5MB 이하만 업로드할 수 있습니다.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    extension = ALLOWED_IMAGE_TYPES[image.content_type]
    filename = f"post-{current_user.id}-{uuid4().hex}{extension}"
    output_path = UPLOAD_DIR / filename
    output_path.write_bytes(data)
    return {"image_url": f"/static/uploads/{filename}"}


@router.post("/thumbnail/candidates", response_model=PostThumbnailCandidatesResponse)
def generate_draft_thumbnail_candidates(
    payload: PostThumbnailCandidatesRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> PostThumbnailCandidatesResponse:
    tag_names = normalize_tag_names(payload.tags)
    try:
        candidates = generate_thumbnail_candidates_for_post(
            db,
            settings,
            payload.title,
            payload.content,
            payload.category,
            tag_names,
            count=3,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PostThumbnailCandidatesResponse.model_validate({"candidates": candidates})


@router.get("/{post_id}", response_model=PostRead)
def read_post(post_id: int, db: Session = Depends(get_db)) -> Post:
    return get_post_or_404(db, post_id)


@router.post("/{post_id}/view", response_model=PostRead)
def increment_post_view(post_id: int, db: Session = Depends(get_db)) -> Post:
    post = get_post_or_404(db, post_id)
    post.view_count += 1
    db.commit()
    return get_post_or_404(db, post_id)


@router.post("/{post_id}/thumbnail", response_model=PostRead)
def generate_post_thumbnail(
    post_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> Post:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can generate a thumbnail")

    result = generate_thumbnail_for_post(
        db,
        settings,
        post.title,
        post.content,
        post.category,
        [tag.name for tag in post.tags],
    )
    post.thumbnail_url = result["structuredContent"]["image_url"]
    db.commit()
    return get_post_or_404(db, post.id)


@router.post("/{post_id}/thumbnail/candidates", response_model=PostThumbnailCandidatesResponse)
def generate_post_thumbnail_candidates(
    post_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> PostThumbnailCandidatesResponse:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can generate thumbnail candidates")

    candidates = generate_thumbnail_candidates_for_post(
        db,
        settings,
        post.title,
        post.content,
        post.category,
        [tag.name for tag in post.tags],
        count=3,
    )
    return PostThumbnailCandidatesResponse.model_validate({"candidates": candidates})


@router.patch("/{post_id}/thumbnail", response_model=PostRead)
def select_post_thumbnail(
    post_id: int,
    payload: PostThumbnailSelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Post:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can select a thumbnail")

    post.thumbnail_url = payload.image_url
    db.commit()
    return get_post_or_404(db, post.id)


@router.put("/{post_id}", response_model=PostRead)
def update_post(
    post_id: int,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> Post:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can update this post")

    tag_names = normalize_tag_names(payload.tags)
    safety_message = post_safety_message_for(payload.title, payload.content, tag_names)
    if safety_message is not None:
        raise HTTPException(status_code=400, detail=safety_message)
    ai_search_summary = make_post_search_summary(
        db,
        settings,
        payload.title,
        payload.content,
        payload.post_type,
        payload.category,
        tag_names,
    )
    post.title = payload.title
    post.content = payload.content
    post.post_type = payload.post_type
    post.category = payload.category
    post.ai_search_summary = ai_search_summary
    post.thumbnail_url = payload.thumbnail_url
    post.tags = get_or_create_tags(db, tag_names)
    db.commit()
    return get_post_or_404(db, post.id)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    post = get_post_or_404(db, post_id)
    if post.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete this post")

    db.delete(post)
    db.commit()
