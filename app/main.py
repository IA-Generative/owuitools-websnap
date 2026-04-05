"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="Browser Use — Web Extraction Service",
        version="0.1.0",
    )

    # CORS
    if settings.CORS_ORIGINS:
        origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Request ID middleware
    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    application.include_router(router)

    @application.on_event("startup")
    async def startup_validation():
        missing = settings.validate_features()
        if missing:
            logger.error("Missing required config for enabled features: %s", missing)
        logger.info("Browser Use starting — features: %s", settings.enabled_features)

    return application


app = create_app()
