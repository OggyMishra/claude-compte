"""FastAPI application serving the dashboard and usage API."""

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from claude_compte.optimizer import generate_optimizations
from claude_compte.parser import parse_all_sessions

STATIC_DIR = Path(__file__).parent / "static"

_cached_data: dict | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="claude-compte")

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/api/usage")
    async def usage(refresh: bool = Query(False)):
        global _cached_data
        if _cached_data is None or refresh:
            data = parse_all_sessions(force_refresh=refresh)
            data["optimizations"] = generate_optimizations(data)
            _cached_data = data
        return _cached_data

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app
