from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, comments, posts, tags
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="Board Simple API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(settings.frontend_origin).rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(tags.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
