"""Tests for fee-schedule construction and meal-cost estimation.

The vector-file test at the bottom runs the shared fixtures that
src/utils/mealCost.test.js also runs, guaranteeing the Python and JS
implementations agree to the cent.
"""

import json
from pathlib import Path

from app.models.food import FeeSchedule, Platform, PlatformResult
from app.services.pricing import (
    build_fee_schedule,
    compute_service_fee,
    compute_small_order_fee,
    ensure_fee_schedule,
    estimate_meal_cost,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _pr(**overrides) -> PlatformResult:
    base = dict(
        platform=Platform.UBER_EATS,
        restaurant_name="Testaurant",
        restaurant_id="t1",
        restaurant_url="https://x",
        delivery_fee=1.99,
        service_fee=0.0,
        estimated_delivery_minutes=30,
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return PlatformResult(**base)


# ---------- build_fee_schedule ----------


def test_defaults_fill_missing_fields_and_are_marked_estimated():
    fs = build_fee_schedule("doordash", delivery_fee=2.99)
    assert fs.delivery_fee == 2.99
    assert fs.service_fee_pct == 15.0
    assert fs.service_fee_min == 3.00
    assert fs.small_order_fee == 2.50
    assert fs.small_order_threshold == 10.00
    assert set(fs.estimated_fields) == {
        "service_fee_pct",
        "service_fee_min",
        "small_order_fee",
        "small_order_threshold",
    }


def test_exact_service_pct_suppresses_service_fee_defaults():
    # Grubhub exposes basis_points; no estimated floor may be grafted on.
    fs = build_fee_schedule("grubhub", delivery_fee=0.99, service_fee_pct=10.35)
    assert fs.service_fee_pct == 10.35
    assert fs.service_fee_min is None
    assert all(not f.startswith("service_fee") for f in fs.estimated_fields)


def test_scraped_flat_service_fee_suppresses_pct_defaults():
    fs = build_fee_schedule("uber_eats", delivery_fee=0.0, service_fee_flat=2.49)
    assert fs.service_fee_flat == 2.49
    assert fs.service_fee_pct is None
    # Small-order defaults still apply — they're independent of service fee.
    assert fs.small_order_fee == 2.00
    assert "small_order_fee" in fs.estimated_fields


def test_unknown_platform_gets_no_defaults():
    fs = build_fee_schedule("eatstreet", delivery_fee=3.49)
    assert fs.service_fee_pct is None
    assert fs.estimated_fields == []


# ---------- ensure_fee_schedule ----------


def test_ensure_fee_schedule_fills_from_flat_fields():
    r = _pr(delivery_fee=3.49, service_fee=0.0, minimum_order=12.0)
    ensure_fee_schedule(r)
    assert r.fee_schedule.delivery_fee == 3.49
    assert r.fee_schedule.minimum_order == 12.0
    # service_fee == 0 means "not exposed": estimated pct fills in.
    assert r.fee_schedule.service_fee_pct == 15.0


def test_ensure_fee_schedule_respects_existing_schedule():
    fs = FeeSchedule(delivery_fee=0.49, service_fee_pct=5.0)
    r = _pr(fee_schedule=fs)
    ensure_fee_schedule(r)
    assert r.fee_schedule is fs


def test_ensure_fee_schedule_keeps_scraped_flat_service_fee():
    r = _pr(platform=Platform.GRUBHUB, service_fee=1.25)
    ensure_fee_schedule(r)
    assert r.fee_schedule.service_fee_flat == 1.25
    assert r.fee_schedule.service_fee_pct is None


# ---------- fee math ----------


def test_service_fee_pct_with_floor_and_cap():
    fs = FeeSchedule(service_fee_pct=15.0, service_fee_min=3.0, service_fee_max=9.0)
    assert compute_service_fee(fs, 10.0) == 3.0    # 1.50 -> floor
    assert compute_service_fee(fs, 40.0) == 6.0    # 15%
    assert compute_service_fee(fs, 100.0) == 9.0   # 15.00 -> cap


def test_service_fee_flat_only_and_unknown():
    assert compute_service_fee(FeeSchedule(service_fee_flat=2.25), 50.0) == 2.25
    assert compute_service_fee(FeeSchedule(), 50.0) is None


def test_small_order_fee_applies_only_below_threshold():
    fs = FeeSchedule(small_order_fee=2.5, small_order_threshold=10.0)
    assert compute_small_order_fee(fs, 8.0) == 2.5
    assert compute_small_order_fee(fs, 10.0) == 0.0
    assert compute_small_order_fee(fs, 25.0) == 0.0


# ---------- estimate_meal_cost ----------


def test_estimate_typical_doordash_basket():
    fs = build_fee_schedule("doordash", delivery_fee=1.99)
    est = estimate_meal_cost(fs, 25.00)
    assert est["delivery_fee"] == 1.99
    assert est["service_fee"] == 3.75          # 15% of 25
    assert est["small_order_fee"] == 0.0
    assert est["tax"] == 0.0 and est["tax_rate_pct"] is None
    assert est["total"] == 30.74


def test_estimate_small_basket_triggers_floor_and_small_order_fee():
    fs = build_fee_schedule("doordash", delivery_fee=1.99)
    est = estimate_meal_cost(fs, 8.00)
    assert est["service_fee"] == 3.00          # floor beats 1.20
    assert est["small_order_fee"] == 2.50
    assert est["total"] == 15.49


def test_estimate_with_fallback_tax_rate():
    fs = build_fee_schedule("uber_eats", delivery_fee=2.49)
    est = estimate_meal_cost(fs, 30.00, fallback_tax_rate_pct=9.25)
    assert est["service_fee"] == 4.50
    assert est["tax_rate_pct"] == 9.25
    assert est["tax"] == round(30.00 * 0.0925, 2)
    assert "tax_rate_pct" in est["estimated_fields"]
    assert est["total"] == round(30.00 + 2.49 + 4.50 + est["tax"], 2)


def test_estimate_platform_tax_rate_beats_fallback():
    fs = FeeSchedule(delivery_fee=0.0, tax_rate_pct=6.0)
    est = estimate_meal_cost(fs, 10.00, fallback_tax_rate_pct=9.25)
    assert est["tax_rate_pct"] == 6.0
    assert est["tax"] == 0.60
    assert "tax_rate_pct" not in est["estimated_fields"]


def test_estimate_pickup_drops_delivery_basket_fees():
    fs = build_fee_schedule("doordash", delivery_fee=1.99)
    est = estimate_meal_cost(fs, 20.00, mode="pickup", fallback_tax_rate_pct=8.0)
    assert est["delivery_fee"] == 0.0
    assert est["service_fee"] == 0.0
    assert est["small_order_fee"] == 0.0
    assert est["total"] == round(20.00 + 1.60, 2)


def test_estimate_flags_below_minimum():
    fs = FeeSchedule(delivery_fee=0.0, minimum_order=15.0)
    assert estimate_meal_cost(fs, 10.0)["below_minimum"] is True
    assert estimate_meal_cost(fs, 15.0)["below_minimum"] is False


def test_estimate_unknown_service_fee_stays_none():
    fs = FeeSchedule(delivery_fee=3.49)  # e.g. eatstreet: no service fee data
    est = estimate_meal_cost(fs, 20.0)
    assert est["service_fee"] is None
    assert est["total"] == 23.49  # None treated as 0 in the sum, UI labels it


# ---------- shared parity vectors (mirrored by src/utils/mealCost.test.js) ----------


def test_meal_cost_parity_vectors():
    vectors = json.loads((FIXTURES / "meal_cost_vectors.json").read_text())
    assert len(vectors) >= 8
    for vec in vectors:
        fs = FeeSchedule(**vec["schedule"])
        est = estimate_meal_cost(
            fs,
            vec["subtotal"],
            mode=vec.get("mode", "delivery"),
            fallback_tax_rate_pct=vec.get("fallback_tax_rate_pct"),
        )
        for key, expected in vec["expected"].items():
            assert est[key] == expected, (
                f"vector '{vec['name']}' key '{key}': {est[key]} != {expected}"
            )
