"""Application entry point.

Builds the container and compiles the graph once at startup, so a customer
message never pays for wiring. Policy files are validated here too —
misconfiguration should refuse to boot rather than surface mid-conversation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import router as v1_router
from app.composition.container import build_container
from app.core.errors import AltoError
from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.domain.policies import load_all
from app.graph.builder import compile_graph

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()

    # Fail fast on bad policy. A malformed confidence weight discovered
    # halfway through a customer conversation is far worse than a refused
    # deployment.
    load_all()

    container = build_container(settings)

    checkpointer: Any = None
    try:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
    except ImportError:  # pragma: no cover
        logger.warning("no_checkpointer", note="conversations will not be resumable")

    app.state.container = container
    app.state.graph = compile_graph(container, checkpointer=checkpointer)

    logger.info(
        "api_ready",
        provider=container.router.provider_name,
        retrieval=container.retrieval_enabled,
        catalog=container.catalog.size,
        auto_send=settings.allow_auto_send,
    )
    yield
    logger.info("api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Alto AI Support Orchestrator",
        version="0.1.0",
        description=(
            "Multilingual AI customer-support orchestration for Alto Motors. "
            "Understanding is the only layer that calls a model; routing, "
            "planning and escalation are deterministic business rules."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AltoError)
    async def handle_domain_error(_: Request, exc: AltoError) -> JSONResponse:
        # Domain errors carry their own status and structured context, so the
        # client gets something actionable rather than a bare 500.
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    async def ready(request: Request) -> dict[str, Any]:
        container = request.app.state.container
        return {
            "status": "ready",
            "provider": container.router.provider_name,
            "retrieval_enabled": container.retrieval_enabled,
            "catalog_size": container.catalog.size,
        }

    app.include_router(v1_router)
    return app


app = create_app()
