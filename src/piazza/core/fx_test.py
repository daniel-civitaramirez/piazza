"""Tests for FxProvider."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from piazza.core.fx import (
    FxProvider,
    FxUnavailableError,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


def _mock_transport(rates: dict[str, float], call_counter: list[int]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        call_counter.append(1)
        assert request.url.host == "openexchangerates.org"
        return httpx.Response(200, json={"rates": rates})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_same_currency_short_circuits():
    fx = FxProvider(api_key="", redis=None)
    cents, rate = await fx.convert(1000, "EUR", "EUR")
    assert cents == 1000
    assert rate == Decimal(1)


@pytest.mark.asyncio
async def test_same_currency_normalizes_case():
    fx = FxProvider(api_key="", redis=None)
    cents, rate = await fx.convert(1000, "eur", "EUR")
    assert cents == 1000
    assert rate == Decimal(1)


@pytest.mark.asyncio
async def test_missing_api_key_raises_for_cross_currency():
    fx = FxProvider(api_key="", redis=None)
    with pytest.raises(FxUnavailableError):
        await fx.convert(1000, "EUR", "USD")


@pytest.mark.asyncio
async def test_cross_rate_via_usd_base():
    """openexchangerates returns USD-base rates; cross-rate = to/from."""
    calls: list[int] = []
    transport = _mock_transport({"USD": 1.0, "EUR": 0.92, "GBP": 0.80}, calls)
    client = httpx.AsyncClient(transport=transport)
    fx = FxProvider(api_key="key", redis=None, http_client=client)

    # 100 EUR -> GBP: 100 / 0.92 * 0.80 = 86.96
    cents, rate = await fx.convert(10000, "EUR", "GBP")
    assert cents == 8696  # rounded half-up
    assert abs(rate - Decimal("0.80") / Decimal("0.92")) < Decimal("1e-12")


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_http_call():
    calls: list[int] = []
    transport = _mock_transport({"USD": 1.0, "EUR": 0.90}, calls)
    client = httpx.AsyncClient(transport=transport)
    redis = _FakeRedis()
    fx = FxProvider(api_key="key", redis=redis, http_client=client)

    await fx.convert(100, "USD", "EUR")
    await fx.convert(100, "USD", "EUR")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_unknown_currency_raises():
    transport = _mock_transport({"USD": 1.0, "EUR": 0.90}, [])
    client = httpx.AsyncClient(transport=transport)
    fx = FxProvider(api_key="key", redis=None, http_client=client)

    with pytest.raises(FxUnavailableError):
        await fx.convert(100, "EUR", "XYZ")


@pytest.mark.asyncio
async def test_http_failure_raises():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    fx = FxProvider(api_key="key", redis=None, http_client=client)

    with pytest.raises(FxUnavailableError):
        await fx.convert(100, "EUR", "USD")


@pytest.mark.asyncio
async def test_invalid_currency_input_normalizes():
    fx = FxProvider(api_key="", redis=None)
    with pytest.raises(Exception):
        await fx.convert(100, "dollars", "EUR")


@pytest.mark.asyncio
async def test_cache_round_trip_through_redis():
    """A cached entry surfaces correctly on a fresh provider instance."""
    redis = _FakeRedis()
    redis.store[FxProvider("k", redis)._cache_key()] = json.dumps({
        "USD": "1.0", "EUR": "0.5",
    })
    fx = FxProvider(api_key="k", redis=redis)
    cents, _ = await fx.convert(200, "USD", "EUR")
    assert cents == 100
