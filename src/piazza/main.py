"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from piazza.config.settings import settings

if settings.sentry_dsn:
    import sentry_sdk

    _PII_KEYS = {"text", "sender_jid", "group_jid", "sender_name", "display_name", "content",
                 "message", "description", "push_name", "wa_jid", "admin_jid", "snippet"}

    def _scrub_pii(event, hint):
        """Strip PII from Sentry events before sending."""
        for frame in (event.get("exception", {}).get("values") or []):
            for f in (frame.get("stacktrace", {}).get("frames") or []):
                vs = f.get("vars")
                if vs:
                    for key in _PII_KEYS & vs.keys():
                        vs[key] = "[redacted]"
        return event

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=_scrub_pii,
    )

logger = structlog.get_logger()


def _configure_logging() -> None:
    """Configure structlog with JSON output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize and teardown resources."""
    _configure_logging()

    # Validate encryption key before anything else
    from piazza.core.encryption import validate_key

    if not settings.encryption_key:
        raise RuntimeError("ENCRYPTION_KEY must be configured")
    validate_key(settings.encryption_key_bytes)

    logger.info("app_starting")

    # Initialize DB engine (import triggers creation)
    from arq.connections import create_pool

    from piazza.db.engine import engine
    from piazza.workers.jobs import redis_settings

    try:
        app.state.arq_pool = await create_pool(redis_settings())
        logger.info("arq_pool_initialized")
    except Exception:
        logger.warning("arq_pool_init_failed", exc_info=True)
        app.state.arq_pool = None

    yield

    # Cleanup
    from piazza.messaging.whatsapp import client

    await client.close()

    if app.state.arq_pool is not None:
        await app.state.arq_pool.close()

    await engine.dispose()
    logger.info("app_stopped")


app = FastAPI(title="Piazza", version="0.1.0", lifespan=lifespan)

# Mount webhook router
from piazza.messaging.whatsapp.webhook import router as webhook_router  # noqa: E402

app.include_router(webhook_router)


@app.get("/health")
async def health():
    """Health check endpoint with optional Evolution API connectivity check."""
    result: dict[str, object] = {"status": "ok"}

    if settings.evo_api_url and settings.evo_api_key:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=settings.health_check_timeout) as client:
                resp = await client.get(
                    f"{settings.evo_api_url.rstrip('/')}/instance/fetchInstances",
                    headers={"apikey": settings.evo_api_key},
                )
                result["evolution_api"] = "reachable" if resp.is_success else "error"
        except httpx.HTTPError:
            result["evolution_api"] = "unreachable"

    return result
