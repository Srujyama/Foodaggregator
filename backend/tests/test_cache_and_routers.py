"""Tests for cache key behavior and router-level filtering/mode handling."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.food import (
    AggregatedResult,
    Platform,
    PlatformResult,
)
from app.services import cache as cache_module


def _now():
    return datetime.now(timezone.utc).isoformat()


def _platform(p: Platform, name="X", rid="r1", df=0.0, sf=0.0):
    return PlatformResult(
        platform=p,
        restaurant_name=name,
        restaurant_id=rid,
        restaurant_url="https://x",
        delivery_fee=df,
        service_fee=sf,
        estimated_delivery_minutes=20,
        fetched_at=_now(),
    )


def _agg(platforms, name="Taco Bell"):
    return AggregatedResult(
        query="taco bell",
        location="19713",
        restaurant_name=name,
        platforms=platforms,
    )


# ---------- cache key ----------


def test_cache_key_differs_by_mode():
    k_d = cache_module._make_key("taco bell", "19713", "delivery")
    k_p = cache_module._make_key("taco bell", "19713", "pickup")
    assert k_d != k_p


def test_cache_key_default_mode_is_delivery():
    assert cache_module._make_key("x", "y") == cache_module._make_key("x", "y", "delivery")


def test_cache_key_normalizes_case_and_whitespace():
    a = cache_module._make_key("  Taco Bell ", "19713", "delivery")
    b = cache_module._make_key("taco bell", "19713", "delivery")
    assert a == b


@pytest.mark.asyncio
async def test_memory_cache_round_trip_separates_modes():
    cache_module._memory_cache.clear()
    await cache_module.set_cached("taco", "19713", [{"x": 1}], "delivery")
    await cache_module.set_cached("taco", "19713", [{"x": 2}], "pickup")
    d = await cache_module.get_cached("taco", "19713", "delivery")
    p = await cache_module.get_cached("taco", "19713", "pickup")
    assert d == [{"x": 1}]
    assert p == [{"x": 2}]


# ---------- in-flight request coalescing ----------


@pytest.mark.asyncio
async def test_coalesce_shares_one_factory_run():
    import asyncio

    calls = 0

    async def slow_factory():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"data": calls}

    results = await asyncio.gather(
        cache_module.coalesce("k1", slow_factory),
        cache_module.coalesce("k1", slow_factory),
        cache_module.coalesce("k1", slow_factory),
    )
    assert calls == 1
    assert all(r == {"data": 1} for r in results)
    # All waiters got the SAME object — callers must copy before mutating.
    assert results[0] is results[1]


@pytest.mark.asyncio
async def test_coalesce_different_keys_run_separately():
    import asyncio

    calls = []

    def make_factory(tag):
        async def factory():
            calls.append(tag)
            await asyncio.sleep(0.01)
            return tag
        return factory

    a, b = await asyncio.gather(
        cache_module.coalesce("key-a", make_factory("a")),
        cache_module.coalesce("key-b", make_factory("b")),
    )
    assert (a, b) == ("a", "b")
    assert sorted(calls) == ["a", "b"]


@pytest.mark.asyncio
async def test_coalesce_failure_propagates_then_retries_fresh():
    import asyncio

    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.01)
        if attempts == 1:
            raise RuntimeError("scrape blew up")
        return "ok"

    waiters = await asyncio.gather(
        cache_module.coalesce("flaky-key", flaky),
        cache_module.coalesce("flaky-key", flaky),
        return_exceptions=True,
    )
    assert all(isinstance(w, RuntimeError) for w in waiters)
    # The failed task must not be sticky: the next call retries.
    assert await cache_module.coalesce("flaky-key", flaky) == "ok"
    assert attempts == 2


def test_search_filter_does_not_corrupt_shared_results(client):
    """Coalesced waiters share result objects; a platform-filtered request
    must not strip platforms from what other requests (or the cache) see."""
    c, _ = client
    first = c.get("/api/search?q=x&location=y&platforms=doordash").json()
    assert [p["platform"] for p in first["results"][0]["platforms"]] == ["doordash"]
    # Same search again (cache hit) must still have all three platforms.
    second = c.get("/api/search?q=x&location=y").json()
    assert len(second["results"][0]["platforms"]) == 3


# ---------- search router ----------


@pytest.fixture
def client(monkeypatch):
    """Mount FastAPI in-process, with the AggregatorService stubbed and
    cache cleared between tests."""
    cache_module._memory_cache.clear()

    captured = {}

    async def fake_search(self, q, location, timeout=20.0, mode="delivery", with_status=False):
        captured["mode"] = mode
        captured["query"] = q
        captured["location"] = location
        results = [
            _agg([
                _platform(Platform.UBER_EATS, df=2.99, sf=1.0, rid="ue"),
                _platform(Platform.DOORDASH, df=0.99, sf=0.5, rid="dd"),
                _platform(Platform.GRUBHUB, df=4.99, sf=0.0, rid="gh"),
            ])
        ]
        if with_status:
            status = {"uber_eats": "ok", "doordash": "ok", "grubhub": "ok"}
            return results, status
        return results

    async def fake_get_restaurant(self, name, location, mode="delivery"):
        captured["detail_mode"] = mode
        return _agg([_platform(Platform.UBER_EATS, name=name, rid="ue")], name=name)

    from app.services.aggregator import AggregatorService
    monkeypatch.setattr(AggregatorService, "search", fake_search)
    monkeypatch.setattr(AggregatorService, "get_restaurant", fake_get_restaurant)

    from app.main import app
    return TestClient(app), captured


def test_search_endpoint_returns_results(client):
    c, captured = client
    r = c.get("/api/search?q=Taco+Bell&location=19713")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["results"][0]["platforms"]) == 3
    assert captured["mode"] == "delivery"


def test_search_endpoint_passes_mode_through(client):
    c, captured = client
    r = c.get("/api/search?q=x&location=y&mode=pickup")
    assert r.status_code == 200
    assert captured["mode"] == "pickup"


def test_search_endpoint_validates_invalid_mode_falls_back_to_delivery(client):
    c, captured = client
    r = c.get("/api/search?q=x&location=y&mode=carrierpigeon")
    assert r.status_code == 200
    assert captured["mode"] == "delivery"


def test_search_endpoint_applies_platform_filter_on_first_call(client):
    c, _ = client
    r = c.get("/api/search?q=x&location=y&platforms=doordash")
    body = r.json()
    plats = [p["platform"] for p in body["results"][0]["platforms"]]
    assert plats == ["doordash"]


def test_search_endpoint_applies_platform_filter_on_cache_hit(client):
    """Original bug: cache short-circuit returned ALL platforms even when
    the request asked for a subset. Hit twice and assert the filter still
    applies on the cached second response."""
    c, _ = client
    first = c.get("/api/search?q=x&location=y").json()
    assert not first["cached"]
    second = c.get("/api/search?q=x&location=y&platforms=grubhub").json()
    assert second["cached"] is True
    plats = [p["platform"] for p in second["results"][0]["platforms"]]
    assert plats == ["grubhub"]


def test_search_endpoint_separates_cache_by_mode(client):
    c, _ = client
    a = c.get("/api/search?q=x&location=y&mode=delivery").json()
    assert not a["cached"]
    b = c.get("/api/search?q=x&location=y&mode=pickup").json()
    # Pickup mode must miss the delivery cache.
    assert not b["cached"]
    third = c.get("/api/search?q=x&location=y&mode=delivery").json()
    assert third["cached"] is True


def test_restaurant_endpoint_passes_mode(client):
    c, captured = client
    r = c.get("/api/restaurant/Taco%20Bell?location=19713&mode=pickup")
    assert r.status_code == 200
    assert captured["detail_mode"] == "pickup"


def test_restaurant_endpoint_404_when_missing(monkeypatch):
    cache_module._memory_cache.clear()

    async def empty_get(self, name, location, mode="delivery"):
        return None

    from app.services.aggregator import AggregatorService
    monkeypatch.setattr(AggregatorService, "get_restaurant", empty_get)

    from app.main import app
    c = TestClient(app)
    r = c.get("/api/restaurant/Nope?location=19713")
    assert r.status_code == 404
