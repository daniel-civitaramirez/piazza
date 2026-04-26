"""Foreign-exchange conversion with Redis-cached daily rates.

Backed by openexchangerates.org (USD-base, hourly free tier). One API
call per cache window (default 1 hour) serves the whole rate table for
that window. Rates are not snapshotted on the expense — balances and
conversions read whatever is current, by design.

Composition: instantiate `FxProvider(api_key, redis, cache_ttl)` at app
startup via `init_fx_provider(...)`. Handlers fetch the singleton with
`get_fx_provider()`. Tests swap in a fake via `set_fx_provider(...)`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

import httpx
import structlog

from piazza.core.currency import normalize as normalize_currency

logger = structlog.get_logger()

OPENEXCHANGERATES_LATEST_URL = "https://openexchangerates.org/api/latest.json"
DEFAULT_CACHE_TTL_SECONDS = 3600


class FxUnavailableError(RuntimeError):
    """Raised when a non-trivial conversion is requested but rates are unavailable."""


class _RedisLike(Protocol):
    async def get(self, key: str) -> bytes | str | None: ...
    async def set(self, key: str, value: str, ex: int | None = ...) -> object: ...


class FxProvider:
    """Convert amounts between ISO-4217 currencies at the latest cached rate."""

    def __init__(
        self,
        api_key: str,
        redis: _RedisLike | None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._redis = redis
        self._cache_ttl = cache_ttl_seconds
        self._http = http_client

    async def convert(
        self, amount_cents: int, from_currency: str, to_currency: str
    ) -> tuple[int, Decimal]:
        """Convert `amount_cents` from `from_currency` to `to_currency`.

        Returns (converted_cents, rate). Rate is the multiplicative factor
        such that `amount_cents * rate ≈ converted_cents`.

        Same-currency conversions short-circuit with rate=1 and never call
        the FX provider.
        """
        from_c = normalize_currency(from_currency)
        to_c = normalize_currency(to_currency)
        if from_c == to_c:
            return amount_cents, Decimal(1)

        rates = await self._get_rates()
        if from_c not in rates or to_c not in rates:
            raise FxUnavailableError(
                f"FX rate missing for {from_c} or {to_c}"
            )

        # openexchangerates returns rates relative to USD. Cross-rate:
        #   X→Y = (1/X_per_USD) * Y_per_USD  ==  Y_per_USD / X_per_USD
        rate = rates[to_c] / rates[from_c]
        converted = (Decimal(amount_cents) * rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        return int(converted), rate

    async def _get_rates(self) -> dict[str, Decimal]:
        if not self._api_key:
            raise FxUnavailableError("OPENEXCHANGERATES_KEY is not configured")

        cache_key = self._cache_key()
        if self._redis is not None:
            cached = await self._redis.get(cache_key)
            if cached is not None:
                payload = cached.decode() if isinstance(cached, bytes) else cached
                return {k: Decimal(v) for k, v in json.loads(payload).items()}

        rates = await self._fetch_rates()

        if self._redis is not None:
            serialized = json.dumps({k: str(v) for k, v in rates.items()})
            await self._redis.set(cache_key, serialized, ex=self._cache_ttl)

        return rates

    async def _fetch_rates(self) -> dict[str, Decimal]:
        client = self._http or httpx.AsyncClient(timeout=5.0)
        try:
            response = await client.get(
                OPENEXCHANGERATES_LATEST_URL,
                params={"app_id": self._api_key},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("fx_fetch_failed", error=str(exc))
            raise FxUnavailableError("openexchangerates request failed") from exc
        finally:
            if self._http is None:
                await client.aclose()

        rates_raw = data.get("rates")
        if not isinstance(rates_raw, dict):
            raise FxUnavailableError("openexchangerates returned no rates")
        return {k: Decimal(str(v)) for k, v in rates_raw.items()}

    def _cache_key(self) -> str:
        bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
        return f"fx:rates:{bucket}"


# ---------- Module-level composition root ----------

_provider: FxProvider | None = None


def init_fx_provider(provider: FxProvider) -> None:
    """Install the process-wide FX provider. Called from app startup."""
    global _provider
    _provider = provider


def set_fx_provider(provider: FxProvider | None) -> None:
    """Swap the FX provider — for tests."""
    global _provider
    _provider = provider


def get_fx_provider() -> FxProvider:
    """Fetch the installed FX provider, or raise if none was wired."""
    if _provider is None:
        raise FxUnavailableError("FX provider not initialized")
    return _provider
