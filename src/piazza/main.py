"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import sentry_sdk
import structlog
from arq.connections import create_pool
from fastapi import FastAPI
from redis.asyncio import Redis as RedisClient

from piazza.config.settings import settings
from piazza.core.encryption import validate_key
from piazza.core.fx import FxProvider, init_fx_provider
from piazza.db.engine import engine
from piazza.messaging.whatsapp import client as whatsapp_client
from piazza.messaging.whatsapp.webhook import router as webhook_router
from piazza.workers.jobs import redis_settings

_PII_KEYS = {"text", "sender_jid", "group_jid", "sender_name", "display_name", "content",
             "message", "description", "push_name", "wa_jid", "admin_jid", "snippet"}


def _scrub_pii(event, hint):
    for frame in (event.get("exception", {}).get("values") or []):
        for f in (frame.get("stacktrace", {}).get("frames") or []):
            vs = f.get("vars")
            if vs:
                for key in _PII_KEYS & vs.keys():
                    vs[key] = "[redacted]"
    return event


if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=_scrub_pii,
    )


logger = structlog.get_logger()


def _configure_logging() -> None:
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
    _configure_logging()

    if not settings.encryption_key:
        raise RuntimeError("ENCRYPTION_KEY must be configured")
    validate_key(settings.encryption_key_bytes)

    logger.info("app_starting")

    try:
        app.state.arq_pool = await create_pool(redis_settings())
        logger.info("arq_pool_initialized")
    except Exception:
        logger.warning("arq_pool_init_failed", exc_info=True)
        app.state.arq_pool = None

    fx_redis = RedisClient.from_url(
        settings.redis_url,
        password=settings.redis_password or None,
    )
    init_fx_provider(
        FxProvider(
            api_key=settings.openexchangerates_key,
            redis=fx_redis,
            cache_ttl_seconds=settings.fx_cache_ttl_seconds,
        )
    )
    logger.info("fx_provider_initialized", configured=bool(settings.openexchangerates_key))

    yield

    await whatsapp_client.close()

    if app.state.arq_pool is not None:
        await app.state.arq_pool.close()

    await engine.dispose()
    logger.info("app_stopped")


app = FastAPI(title="Piazza", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    """Health check endpoint with optional Evolution API connectivity check."""
    result: dict[str, object] = {"status": "ok"}

    if settings.evo_api_url and settings.evo_api_key:
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
