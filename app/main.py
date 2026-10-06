"""FastAPI application factory and entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import init_db
from app.exceptions import register_exception_handlers
from app.routers import files

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialised; uploads dir: %s", settings.upload_dir)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Upload a geospatial file (Shapefile `.zip` or `.kml`), extract its "
            "features, and compute area/length measurements with correct CRS "
            "handling (geographic coordinates are projected before measurement)."
        ),
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(files.router, prefix="")

    @app.get("/", tags=["health"])
    def root() -> dict:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
