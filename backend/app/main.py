from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, comments, posts, rag, tags
from app.core.config import get_settings
from app.mcp.server import create_board_mcp


def create_app() -> FastAPI:
    settings = get_settings()
    board_mcp = create_board_mcp()
    mcp_app = board_mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with board_mcp.session_manager.run():
            yield

    app = FastAPI(title="Board Simple API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(settings.frontend_origin).rstrip("/")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(posts.router, prefix="/api")
    app.include_router(comments.router, prefix="/api")
    app.include_router(rag.router, prefix="/api")
    app.include_router(tags.router, prefix="/api")
    app.mount("/mcp", mcp_app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
