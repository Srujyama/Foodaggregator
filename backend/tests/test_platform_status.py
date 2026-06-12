"""Tests for per-platform scrape status (ok/empty/timeout/error) surfaced
through AggregatorService.search(with_status=True) and the search router."""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.food import (
    AggregatedResult,
    Platform,
    PlatformResult,
)
from app.services import cache as cache_module
from app.services.aggregator import AggregatorService


def _now():
    return datetime.now(timezone.utc).isoformat()


def _platform(p: Platform, name="Taco Bell", rid="r1", df=0.0, sf=0.0):
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


# ---------- aggregator with_status ----------


class _StubScraper:
    """Stands in for a platform scraper inside AggregatorService.search.

    behavior: "ok" -> one result, "empty" -> [], "slow" -> sleeps past the
    search timeout so asyncio.wait_for fires, "error" -> raises ValueError.
    """

    def __init__(self, behavior, result=None):
        self.behavior = behavior
        self.result = result

    async def _safe_search(self, query, location, mode="delivery"):
        if self.behavior == "ok":
            return [self.result]
        if self.behavior == "empty":
            return []
        if self.behavior == "slow":
            await asyncio.sleep(2.0)
            return []
        raise ValueError("scraper blew up")

    async def get_restaurant(self, restaurant_id, location, mode="delivery"):
        return None  # skip menu enrichment


def _stubbed_service():
    svc = AggregatorService()
    svc.scrapers = {
        Platform.UBER_EATS: _StubScraper("ok", _platform(Platform.UBER_EATS, rid="ue")),
        Platform.DOORDASH: _StubScraper("empty"),
        Platform.GRUBHUB: _StubScraper("slow"),
        Platform.POSTMATES: _StubScraper("error"),
    }
    return svc


async def test_with_status_maps_ok_empty_timeout_error():
    svc = _stubbed_service()
    results, status = await svc.search(
        "taco bell", "19713", timeout=0.1, with_status=True
    )
    assert status == {
        "uber_eats": "ok",
        "doordash": "empty",
        "grubhub": "timeout",
        "postmates": "error",
    }
    assert len(results) == 1
    assert results[0].restaurant_name == "Taco Bell"


async def test_with_status_returned_even_when_no_results():
    svc = AggregatorService()
    svc.scrapers = {
        Platform.UBER_EATS: _StubScraper("empty"),
        Platform.DOORDASH: _StubScraper("error"),
    }
    results, status = await svc.search("x", "y", timeout=0.1, with_status=True)
    assert results == []
    assert status == {"uber_eats": "empty", "doordash": "error"}


async def test_search_default_still_returns_bare_list():
    svc = _stubbed_service()
    results = await svc.search("taco bell", "19713", timeout=0.1)
    assert isinstance(results, list)
    assert len(results) == 1


# ---------- router ----------


_STATUS = {"uber_eats": "ok", "doordash": "timeout", "grubhub": "empty"}


@pytest.fixture
def client(monkeypatch):
    cache_module._memory_cache.clear()

    async def fake_search(self, q, location, timeout=20.0, mode="delivery", with_status=False):
        results = [
            _agg([
                _platform(Platform.UBER_EATS, rid="ue"),
                _platform(Platform.DOORDASH, rid="dd"),
            ])
        ]
        if with_status:
            return results, dict(_STATUS)
        return results

    monkeypatch.setattr(AggregatorService, "search", fake_search)

    from app.main import app
    return TestClient(app)


def test_fresh_response_includes_platform_status(client):
    body = client.get("/api/search?q=taco&location=19713").json()
    assert not body["cached"]
    assert body["platform_status"] == _STATUS
    assert body["total"] == 1


def test_legacy_bare_list_cache_served_with_empty_status(client):
    # Old Firestore entries cached a bare list of result dicts.
    legacy = [_agg([_platform(Platform.UBER_EATS, rid="ue")]).model_dump()]
    key = cache_module._make_key("legacy", "19713", "delivery")
    cache_module.set_in_memory(key, legacy)

    body = client.get("/api/search?q=legacy&location=19713").json()
    assert body["cached"] is True
    assert body["platform_status"] == {}
    assert body["total"] == 1
    assert body["results"][0]["restaurant_name"] == "Taco Bell"


def test_dict_cache_round_trips_platform_status(client):
    first = client.get("/api/search?q=taco&location=19713").json()
    assert not first["cached"]
    second = client.get("/api/search?q=taco&location=19713").json()
    assert second["cached"] is True
    assert second["platform_status"] == _STATUS
    assert second["total"] == 1
