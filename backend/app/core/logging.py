"""Structured logging.

JSON in production so logs are queryable; human-readable in development.
Log lines are for operators — the analytical record of what the pipeline did
lives in the `spans` table, which is wide, queryable and durable.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.core.settings import get_settings

# Fields that must never reach a log line. Inquiries routinely carry names,
# phone numbers and salary figures, and logs are the easiest place for that to
# leak somewhere it was never meant to go.
REDACTED_KEYS = frozenset(
    {
        "password", "token", "api_key", "authorization", "jwt_secret",
        "phone", "contact_phone", "email", "contact_email",
        "monthly_income", "raw_text",
    }
)
REDACTION = "[redacted]"


def _redact(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event):
        if key.lower() in REDACTED_KEYS and event[key] is not None:
            event[key] = REDACTION
    return event


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )

    # These libraries are chatty at INFO and drown out our own lines.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "qdrant_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
