from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import ai, auth, comments, mcp, posts, rag, tags
from app.core.config import get_settings

settings = get_settings()
allowed_frontend_origin = str(settings.frontend_origin).rstrip("/")
unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}

docs_url = None if settings.app_env == "production" else "/docs"
redoc_url = None if settings.app_env == "production" else "/redoc"
openapi_url = None if settings.app_env == "production" else "/openapi.json"

app = FastAPI(
    title="Board Simple API",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[allowed_frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def enforce_state_changing_origin(request: Request, call_next):
    if _request_body_too_large(request):
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body is too large"},
        )
    if request.method in unsafe_methods:
        origin = request.headers.get("origin")
        if origin != allowed_frontend_origin:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid request origin"},
            )
    return await call_next(request)


def _request_body_too_large(request: Request) -> bool:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return False
    try:
        body_size = int(content_length)
    except ValueError:
        return False
    return body_size > settings.api_request_body_max_bytes


app.include_router(auth.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(tags.router, prefix="/api")
app.include_router(mcp.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(rag.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
