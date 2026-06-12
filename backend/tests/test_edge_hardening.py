"""Edge-case hardening tests: parser boundary values, outlier-guard boundaries,
cache TTL/coalesce semantics, and router platform filtering."""

import asyncio
import time
from datetime import datetime, timezone

import pytest

from app.models.food import AggregatedResult, Platform, PlatformResult
from app.routers.search import _apply_platform_filter
from app.services import cache as cache_module
from app.services.aggregator import _is_likely_non_restaurant, _reject_price_outliers
from app.services.doordash import _haversine_miles
from app.services.grubhub import _normalize_phone, _parse_restaurant


def _now():
    return datetime.now(timezone.utc).isoformat()


def _platform(p: Platform, name="X", rid="r1"):
    return PlatformResult(
        platform=p,
        restaurant_name=name,
        restaurant_id=rid,
        restaurant_url="https://x",
        delivery_fee=0.0,
        service_fee=0.0,
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


# ---------- grubhub._normalize_phone ----------


def test_normalize_phone_bare_string():
    assert _normalize_phone("3024549938") == "3024549938"


def test_normalize_phone_dict_with_country_code():
    assert _normalize_phone(
        {"country_code": "1", "phone_number": "3024549938"}
    ) == "+1 3024549938"


def test_normalize_phone_dict_missing_number_is_none():
    assert _normalize_phone({}) is None
    assert _normalize_phone({"country_code": "1"}) is None


def test_normalize_phone_empty_string_is_none():
    assert _normalize_phone("") is None
    assert _normalize_phone("   ") is None


def test_normalize_phone_no_double_country_code_prefix():
    # Number already starts with the country code: must not become "+1 13024549938".
    assert _normalize_phone(
        {"country_code": "1", "phone_number": "13024549938"}
    ) == "13024549938"
    # An explicit "+" prefix is also left alone.
    assert _normalize_phone(
        {"country_code": "1", "phone_number": "+13024549938"}
    ) == "+13024549938"


# ---------- grubhub._parse_restaurant cents handling ----------


def test_parse_restaurant_delivery_fee_price_is_cents():
    rd = _parse_restaurant({
        "name": "Tico's Tacos",
        "restaurant_id": "123",
        "delivery_fee": {"price": 300, "currency": "USD"},
    })
    assert rd["delivery_fee"] == 3.00


def test_parse_restaurant_zero_delivery_fee_stays_zero():
    rd = _parse_restaurant({
        "name": "Tico's Tacos",
        "restaurant_id": "123",
        "delivery_fee": {"price": 0, "currency": "USD"},
    })
    assert rd["delivery_fee"] == 0.0


def test_parse_restaurant_delivery_minimum_price_is_cents():
    rd = _parse_restaurant({
        "name": "Tico's Tacos",
        "restaurant_id": "123",
        "delivery_minimum": {"price": 2000, "currency": "USD"},
    })
    assert rd["minimum_order"] == 20.0


# ---------- doordash._haversine_miles ----------


def test_haversine_nyc_to_la():
    dist = _haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
    assert 2440 <= dist <= 2460


def test_haversine_identical_points_is_zero():
    assert _haversine_miles(40.7128, -74.0060, 40.7128, -74.0060) == 0.0


# ---------- aggregator._reject_price_outliers boundaries ----------


def test_outliers_pair_ratio_exactly_at_limit_dropped():
    # Keep-condition is strict < PAIR_MAX_PRICE_RATIO, so exactly 2.5x drops the row.
    prices = {"uber_eats": 4.0, "doordash": 10.0}
    cleaned, ok = _reject_price_outliers(prices)
    assert ok is False
    assert cleaned == prices  # prices come back untouched; caller drops the row


def test_outliers_pair_ratio_just_under_limit_kept():
    prices = {"uber_eats": 100.0, "doordash": 249.0}
    cleaned, ok = _reject_price_outliers(prices)
    assert ok is True
    assert cleaned == prices


def test_outliers_three_platforms_exactly_double_median_dropped():
    # A price at exactly OUTLIER_PRICE_RATIO (2.0x) the median is dropped,
    # matching the docstring: "drop any single price that sits at/above
    # OUTLIER_PRICE_RATIO of the median".
    prices = {"uber_eats": 5.0, "doordash": 10.0, "grubhub": 20.0}
    cleaned, ok = _reject_price_outliers(prices)
    assert ok is True
    assert cleaned == {"uber_eats": 5.0, "doordash": 10.0}


def test_outliers_three_platforms_just_above_double_median_dropped():
    prices = {"uber_eats": 5.0, "doordash": 10.0, "grubhub": 20.01}
    cleaned, ok = _reject_price_outliers(prices)
    assert ok is True
    assert cleaned == {"uber_eats": 5.0, "doordash": 10.0}


def test_outliers_zero_low_price_returned_as_is():
    prices = {"uber_eats": 0.0, "doordash": 5.0}
    cleaned, ok = _reject_price_outliers(prices)
    assert ok is True
    assert cleaned == prices


# ---------- aggregator._is_likely_non_restaurant ----------


def test_non_restaurant_filter_flags_retail_names():
    for name in [
        "CVS Pharmacy",
        "Wild Fork Meat & Seafood Market",
        "7-Eleven",
        "Walgreens",
        "Dollar General",
    ]:
        assert _is_likely_non_restaurant(name) is True, name


def test_non_restaurant_filter_keeps_real_restaurants():
    for name in [
        "Taco Bell",
        "Chipotle Mexican Grill",
        "McDonald's",
        "Shake Shack",
        "Pizza Hut",
    ]:
        assert _is_likely_non_restaurant(name) is False, name


# ---------- cache memory TTL ----------


def test_memory_cache_expires_and_evicts_after_ttl(monkeypatch):
    cache_module._memory_cache.clear()
    cache_module.set_in_memory("ttl-key", {"x": 1})
    assert cache_module.get_from_memory("ttl-key") == {"x": 1}

    base = time.time()
    monkeypatch.setattr(cache_module.time, "time", lambda: base + 301.0)
    assert cache_module.get_from_memory("ttl-key") is None
    # The expired entry must be evicted, not just hidden.
    assert "ttl-key" not in cache_module._memory_cache


# ---------- cache.coalesce cancellation / cleanup ----------


async def test_coalesce_cancelled_waiter_does_not_kill_shared_task():
    calls = 0

    async def slow_factory():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "shared-value"

    key = "cancel-key"
    impatient = asyncio.create_task(
        asyncio.wait_for(cache_module.coalesce(key, slow_factory), timeout=0.01)
    )
    patient = asyncio.create_task(cache_module.coalesce(key, slow_factory))

    with pytest.raises(asyncio.TimeoutError):
        await impatient
    # The timed-out waiter must not have cancelled the underlying scrape.
    assert await patient == "shared-value"
    assert calls == 1


async def test_coalesce_removes_key_from_inflight_after_completion():
    async def factory():
        await asyncio.sleep(0.01)
        return 42

    key = "cleanup-key"
    assert await cache_module.coalesce(key, factory) == 42
    await asyncio.sleep(0)  # let the done-callback run
    assert key not in cache_module._inflight


# ---------- routers.search._apply_platform_filter ----------


def test_platform_filter_keeps_only_requested_platforms():
    results = [
        _agg([
            _platform(Platform.UBER_EATS, rid="ue"),
            _platform(Platform.DOORDASH, rid="dd"),
            _platform(Platform.GRUBHUB, rid="gh"),
        ]),
    ]
    filtered = _apply_platform_filter(results, "doordash,grubhub")
    assert len(filtered) == 1
    assert [p.platform.value for p in filtered[0].platforms] == ["doordash", "grubhub"]


def test_platform_filter_drops_results_with_zero_remaining_platforms():
    results = [
        _agg([_platform(Platform.UBER_EATS, rid="ue")], name="UE Only"),
        _agg([_platform(Platform.DOORDASH, rid="dd")], name="DD Only"),
    ]
    filtered = _apply_platform_filter(results, "doordash")
    assert [r.restaurant_name for r in filtered] == ["DD Only"]


def test_platform_filter_none_or_empty_returns_everything():
    results = [
        _agg([
            _platform(Platform.UBER_EATS, rid="ue"),
            _platform(Platform.DOORDASH, rid="dd"),
        ]),
    ]
    assert _apply_platform_filter(results, None) is results
    assert _apply_platform_filter(results, "") is results
    assert len(results[0].platforms) == 2  # untouched
