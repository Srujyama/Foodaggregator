"""Tests for app.services.aggregator: dedupe, fuzzy grouping, mode plumbing,
menu enrichment merge, ETA reconciliation."""

from datetime import datetime, timezone
from typing import Optional

import pytest

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.aggregator import (
    AggregatorService,
    _build_aggregated,
    _dedupe_postmates_ubereats,
    _fuzzy_group,
    _is_likely_non_restaurant,
)


def _pr(
    platform: Platform,
    name: str = "Taco Bell",
    rid: str = "abc",
    *,
    delivery_fee: float = 0.0,
    service_fee: float = 0.0,
    eta: int = 25,
    eta_max: Optional[int] = None,
    menu: Optional[list[MenuItem]] = None,
    **extra,
) -> PlatformResult:
    return PlatformResult(
        platform=platform,
        restaurant_name=name,
        restaurant_id=rid,
        restaurant_url=f"https://{platform.value}.example/store/{rid}",
        menu_items=menu or [],
        delivery_fee=delivery_fee,
        service_fee=service_fee,
        estimated_delivery_minutes=eta,
        estimated_delivery_minutes_max=eta_max,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        **extra,
    )


# ---------- dedupe ----------


def test_dedupe_drops_postmates_when_uber_has_same_storeuuid():
    rows = [
        _pr(Platform.UBER_EATS, rid="same-uuid"),
        _pr(Platform.POSTMATES, rid="same-uuid"),
        _pr(Platform.DOORDASH, rid="dd-id"),
    ]
    out = _dedupe_postmates_ubereats(rows)
    assert [r.platform for r in out] == [Platform.UBER_EATS, Platform.DOORDASH]


def test_dedupe_keeps_postmates_when_uuid_differs():
    rows = [
        _pr(Platform.UBER_EATS, rid="ue-1"),
        _pr(Platform.POSTMATES, rid="pm-only-1"),
    ]
    out = _dedupe_postmates_ubereats(rows)
    assert {r.platform for r in out} == {Platform.UBER_EATS, Platform.POSTMATES}


def test_dedupe_no_op_when_no_uber_eats():
    rows = [_pr(Platform.POSTMATES, rid="x"), _pr(Platform.DOORDASH, rid="y")]
    assert _dedupe_postmates_ubereats(rows) == rows


# ---------- fuzzy group ----------


def test_fuzzy_group_merges_chipotle_variants():
    rows = [
        _pr(Platform.UBER_EATS, name="Chipotle Mexican Grill", rid="ue1"),
        _pr(Platform.DOORDASH, name="Chipotle", rid="dd1"),
    ]
    groups = _fuzzy_group(rows)
    assert len(groups) == 1
    [group] = groups.values()
    assert {p.platform for p in group} == {Platform.UBER_EATS, Platform.DOORDASH}


def test_fuzzy_group_keeps_same_platform_separate():
    """Two distinct Taco Bell franchises on the same platform must NOT collapse
    into one group, even with identical names."""
    rows = [
        _pr(Platform.UBER_EATS, name="Taco Bell", rid="loc-A"),
        _pr(Platform.UBER_EATS, name="Taco Bell", rid="loc-B"),
        _pr(Platform.DOORDASH, name="Taco Bell", rid="dd-loc"),
    ]
    groups = _fuzzy_group(rows)
    # Two separate groups (each gets the matching DD only once - but DD can't
    # be in two groups simultaneously, so the second UE forms a singleton).
    total = sum(1 for g in groups.values() for _ in g)
    assert total == 3


def test_fuzzy_group_does_not_merge_unrelated_short_tokens():
    """A 4-char name ('Joey') must not be subsumed into 'Joey's Burgers' since
    short prefixes are too noisy to safely merge. (Names ending in 'Pizza'
    are deliberately collapsed by _normalize_name to handle 'Domino's Pizza'
    vs 'Domino's', so we intentionally pick a non-pizza example here.)"""
    rows = [
        _pr(Platform.UBER_EATS, name="Joey", rid="x"),
        _pr(Platform.DOORDASH, name="Joey's Burgers", rid="y"),
    ]
    groups = _fuzzy_group(rows)
    sizes = sorted(len(g) for g in groups.values())
    assert sizes != [2], "fuzzy group merged unrelated 'Joey' with 'Joey's Burgers'"


def test_is_likely_non_restaurant_filters_groceries_and_pharmacies():
    assert _is_likely_non_restaurant("7-Eleven (123 Main St)")
    assert _is_likely_non_restaurant("Walgreens Pharmacy")
    assert _is_likely_non_restaurant("Wawa")
    assert _is_likely_non_restaurant("Royal Farms #42")
    assert not _is_likely_non_restaurant("Taco Bell")
    assert not _is_likely_non_restaurant("Chipotle Mexican Grill")


def test_has_only_non_food_categories_filters_retail_listings():
    from app.services.aggregator import _has_only_non_food_categories

    # Real Berkeley noise: "Power Market" carries only retail tags (actual
    # 7-tag list from the live UberEats store detail).
    assert _has_only_non_food_categories([
        "Convenience", "Alcohol", "Beauty Supply", "Retail",
        "Personal Care", "Hardware", "Pharmacy",
    ])
    assert _has_only_non_food_categories(["Grocery"])
    # Tag-variant spellings must hit via substring matching ("Point Richmond
    # Market" dodged an exact-membership set with these).
    assert _has_only_non_food_categories([
        "Convenience", "Convenience Store with Alcohol", "Liquor Stores", "Alcohol",
    ])
    assert _has_only_non_food_categories([
        "Adult", "Beer", "Convenience", "Alcohol", "Liquor Stores",
    ])
    # Liquor megastore: "Drinks" alone must not save it.
    assert _has_only_non_food_categories([
        "Alcohol", "Liquor", "Liquor Stores", "Wine", "Beer", "Drinks",
    ])
    # A corner market that actually serves food keeps its listing.
    assert not _has_only_non_food_categories(["Convenience", "Deli", "Sandwiches"])
    # "Drinks" alongside a real cuisine tag never filters (boba/juice shops).
    assert not _has_only_non_food_categories(["Bubble Tea", "Drinks"])
    # Any cuisine category marks a real restaurant.
    assert not _has_only_non_food_categories(["Convenience", "Mexican"])
    assert not _has_only_non_food_categories(["Burgers", "Fast Food"])
    # No categories = no signal; never filter on absence.
    assert not _has_only_non_food_categories([])


def test_retail_listing_filtered_even_when_feed_omits_categories():
    """Live bug: UberEats feed results often have categories=[], so the retail
    filter can't judge them at collection time — 'Power Market' only revealed
    Convenience/Alcohol/Retail/Pharmacy after menu enrichment fetched the
    store detail. The post-enrichment pass must drop it."""
    import asyncio
    from datetime import datetime, timezone
    from app.models.food import Platform, PlatformResult
    from app.services.aggregator import AggregatorService

    def _pr(name, cats):
        return PlatformResult(
            platform=Platform.UBER_EATS, restaurant_name=name, restaurant_id=name,
            restaurant_url="https://x", delivery_fee=0, service_fee=0,
            estimated_delivery_minutes=20, categories=cats,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    class Stub:
        PLATFORM_NAME = "uber_eats"

        async def _safe_search(self, q, loc, mode):
            # Feed omits categories for both stores.
            return [_pr("Power Market (3012 Howe Rd )", []), _pr("McDonalds", [])]

        async def get_restaurant(self, rid, loc, mode="delivery"):
            # Store detail reveals what each listing actually is.
            cats = (
                ["Convenience", "Alcohol", "Retail", "Pharmacy"]
                if "Power Market" in rid else ["Burgers", "Fast Food"]
            )
            return _pr(rid, cats)

    svc = AggregatorService()
    svc.scrapers = {Platform.UBER_EATS: Stub()}
    res = asyncio.run(svc.search("mcdonalds", "19713"))
    names = [r.restaurant_name for r in res]
    assert any("McDonalds" in n for n in names)
    assert not any("Power Market" in n for n in names)


def test_is_likely_non_restaurant_filters_big_box_retail():
    # Real UberEats "tacos" search noise that previously leaked into results.
    assert _is_likely_non_restaurant("DICK'S Sporting Goods (2130 Marlton Pike)")
    assert _is_likely_non_restaurant("Ulta Beauty (S Columbus Blvd)")
    assert _is_likely_non_restaurant("The Vitamin Shoppe (31 East City Ave)")
    assert _is_likely_non_restaurant("Wild Fork Meat & Seafood Market")
    assert _is_likely_non_restaurant("Bryn Mawr Beverage (196 Landover Rd)")
    assert _is_likely_non_restaurant("GIANT (N Broad Street)")
    assert _is_likely_non_restaurant("GIANT Heirloom Market")
    assert _is_likely_non_restaurant("At Home (Cherry Hill)")
    # Real taco restaurants must still pass through.
    assert not _is_likely_non_restaurant("Mr. Tacos")
    assert not _is_likely_non_restaurant("Tico's Tacos")


# ---------- _build_aggregated ----------


def test_build_aggregated_picks_lowest_total_as_best():
    group = [
        _pr(Platform.UBER_EATS, delivery_fee=4.99, service_fee=1.00, rid="ue"),
        _pr(Platform.DOORDASH, delivery_fee=0.99, service_fee=0.50, rid="dd"),
        _pr(Platform.GRUBHUB, delivery_fee=2.99, service_fee=2.00, rid="gh"),
    ]
    agg = _build_aggregated("Taco Bell", "19713", group)
    assert agg.best_deal_platform == Platform.DOORDASH


def test_build_aggregated_uses_longest_name_as_canonical():
    group = [
        _pr(Platform.UBER_EATS, name="Taco Bell (379 E Chestnut Hill Plaza Rd)"),
        _pr(Platform.DOORDASH, name="Taco Bell"),
    ]
    agg = _build_aggregated("Taco Bell", "19713", group)
    assert "Chestnut Hill" in agg.restaurant_name


def test_build_aggregated_menu_comparison_sorted_by_savings():
    items_ue = [MenuItem(name="Beef Taco", price=2.50), MenuItem(name="Chalupa", price=4.00)]
    items_dd = [MenuItem(name="Beef Taco", price=2.99), MenuItem(name="Chalupa", price=4.00)]
    group = [
        _pr(Platform.UBER_EATS, menu=items_ue, rid="ue"),
        _pr(Platform.DOORDASH, menu=items_dd, rid="dd"),
    ]
    agg = _build_aggregated("Tacos", "19713", group)
    # Beef Taco has a price difference, Chalupa doesn't.
    diffs = [c for c in agg.menu_comparison if c.price_difference > 0]
    assert diffs, "expected a menu item with price difference"
    assert diffs[0].item_name.lower().startswith("beef taco")
    assert diffs[0].cheapest_platform == Platform.UBER_EATS.value


# ---------- price-outlier rejection in menu comparison ----------


def test_reject_price_outliers_drops_single_outlier_with_three_platforms():
    from app.services.aggregator import _reject_price_outliers

    cleaned, ok = _reject_price_outliers(
        {"uber_eats": 3.60, "doordash": 3.60, "grubhub": 7.65}
    )
    assert ok is True
    assert "grubhub" not in cleaned  # the 2.1x outlier is dropped
    assert set(cleaned) == {"uber_eats", "doordash"}


def test_reject_price_outliers_drops_two_platform_row_above_ratio():
    from app.services.aggregator import _reject_price_outliers

    _, ok = _reject_price_outliers({"uber_eats": 3.00, "doordash": 9.00})
    assert ok is False  # 3x gap on a 2-platform row -> drop the whole row


def test_reject_price_outliers_keeps_consensus():
    from app.services.aggregator import _reject_price_outliers

    cleaned, ok = _reject_price_outliers(
        {"uber_eats": 12.15, "doordash": 12.15, "caviar": 12.15}
    )
    assert ok is True
    assert len(cleaned) == 3


def test_menu_comparison_excludes_outlier_priced_item():
    """A bundle/size mismatch (one platform 3x the other) must not appear as a
    same-item price comparison — it inflates savings and markup nonsensically."""
    items_ue = [MenuItem(name="Queso", price=3.00)]
    items_dd = [MenuItem(name="Queso", price=9.50)]  # really a "Large Chips & Queso"
    group = [
        _pr(Platform.UBER_EATS, menu=items_ue, rid="ue"),
        _pr(Platform.DOORDASH, menu=items_dd, rid="dd"),
    ]
    agg = _build_aggregated("Mex", "19713", group)
    assert all(
        "queso" not in c.item_name.lower() for c in agg.menu_comparison
    ), "outlier-priced 2-platform row should be excluded"


# ---------- _enrich_menus merge logic ----------


@pytest.mark.asyncio
async def test_enrich_menus_reconciles_eta_when_detail_returns_real_value():
    """When the feed left eta=30 (fallback) and the detail returns a real
    smaller value, the merge should adopt the detail's value rather than
    leaving an inverted range."""
    from app.services.aggregator import AggregatorService

    feed_row = _pr(Platform.UBER_EATS, eta=30, rid="taco-uuid")
    agg = AggregatorService.__new__(AggregatorService)

    # Stub one scraper that returns a detail with a small ETA.
    class FakeScraper:
        async def get_restaurant(self, rid, location, mode):
            return _pr(Platform.UBER_EATS, eta=10, eta_max=26, rid=rid,
                      menu=[MenuItem(name="Taco", price=1.99)])

    agg.scrapers = {Platform.UBER_EATS: FakeScraper()}

    aggregated = [_build_aggregated("Taco Bell", "19713", [feed_row])]
    await agg._enrich_menus(aggregated, "19713")

    p = aggregated[0].platforms[0]
    assert p.estimated_delivery_minutes == 10
    assert p.estimated_delivery_minutes_max == 26
    assert p.menu_items, "menu items should have been merged in"


@pytest.mark.asyncio
async def test_enrich_menus_drops_inverted_max_from_detail():
    """If detail comes back with eta_min > eta_max (sometimes happens when the
    detail uses a different lat/lng context), the merge should clear eta_max
    rather than store the inverted range."""
    feed_row = _pr(Platform.UBER_EATS, eta=20, rid="x")
    agg = AggregatorService.__new__(AggregatorService)

    class FakeScraper:
        async def get_restaurant(self, rid, location, mode):
            r = _pr(Platform.UBER_EATS, eta=30, eta_max=10, rid=rid,
                    menu=[MenuItem(name="x", price=1.0)])
            return r

    agg.scrapers = {Platform.UBER_EATS: FakeScraper()}
    aggregated = [_build_aggregated("X", "19713", [feed_row])]
    await agg._enrich_menus(aggregated, "19713")
    p = aggregated[0].platforms[0]
    assert p.estimated_delivery_minutes == 30
    assert p.estimated_delivery_minutes_max is None


@pytest.mark.asyncio
async def test_enrich_menus_copies_consumer_fields():
    feed_row = _pr(Platform.UBER_EATS, rid="x")
    agg = AggregatorService.__new__(AggregatorService)

    class FakeScraper:
        async def get_restaurant(self, rid, location, mode):
            return _pr(
                Platform.UBER_EATS, rid=rid,
                menu=[MenuItem(name="m", price=1.0)],
                address="379 E Chestnut Hill Rd, Newark, DE 19713",
                phone="+13024549938",
                categories=["Mexican", "Tacos"],
                price_bucket="$",
                distance_text="0.6 mi",
                hours_today_text="Open until 11 PM",
                is_open=True,
                accepting_orders=True,
                is_within_delivery_range=True,
                allergen_disclaimer_html="<span>...</span>",
            )

    agg.scrapers = {Platform.UBER_EATS: FakeScraper()}
    aggregated = [_build_aggregated("X", "19713", [feed_row])]
    await agg._enrich_menus(aggregated, "19713")
    p = aggregated[0].platforms[0]
    assert p.address.startswith("379")
    assert p.phone == "+13024549938"
    assert "Mexican" in p.categories
    assert p.price_bucket == "$"
    assert p.distance_text == "0.6 mi"
    assert p.hours_today_text == "Open until 11 PM"
    assert p.is_open is True
    assert p.allergen_disclaimer_html


@pytest.mark.asyncio
async def test_enrich_menus_preserves_platform_when_detail_fails():
    """A scraper detail call that throws or returns None must not blank out
    the existing PlatformResult."""
    feed_row = _pr(Platform.UBER_EATS, rid="x", delivery_fee=2.99, service_fee=1.0)
    agg = AggregatorService.__new__(AggregatorService)

    class BoomScraper:
        async def get_restaurant(self, rid, location, mode):
            raise RuntimeError("simulated network failure")

    agg.scrapers = {Platform.UBER_EATS: BoomScraper()}
    aggregated = [_build_aggregated("X", "19713", [feed_row])]
    await agg._enrich_menus(aggregated, "19713")
    p = aggregated[0].platforms[0]
    assert p.delivery_fee == 2.99  # untouched
    assert p.service_fee == 1.0


@pytest.mark.asyncio
async def test_enrich_reconciles_adopted_detail_schedule_with_flat_fees():
    """A detail parse that found no delivery fee ships a $0 fee schedule;
    adopting it must not clobber the feed's real fee — the schedule gets
    backfilled from the guarded flat field."""
    from app.models.food import FeeSchedule

    feed_row = _pr(Platform.UBER_EATS, rid="x", delivery_fee=2.99)
    feed_row.fee_schedule = FeeSchedule(delivery_fee=2.99, service_fee_pct=15.0)
    agg = AggregatorService.__new__(AggregatorService)

    class FakeScraper:
        async def get_restaurant(self, rid, location, mode):
            detail = _pr(
                Platform.UBER_EATS, rid=rid,
                menu=[MenuItem(name="m", price=1.0)],
                delivery_fee=0.0,
            )
            detail.fee_schedule = FeeSchedule(
                delivery_fee=0.0, service_fee_pct=15.0, minimum_order=None
            )
            return detail

    agg.scrapers = {Platform.UBER_EATS: FakeScraper()}
    aggregated = [_build_aggregated("X", "19713", [feed_row])]
    await agg._enrich_menus(aggregated, "19713")
    p = aggregated[0].platforms[0]
    assert p.delivery_fee == 2.99  # flat guard kept the feed fee
    assert p.fee_schedule.delivery_fee == 2.99  # schedule reconciled to match


@pytest.mark.asyncio
async def test_enrich_keeps_detail_schedule_fee_when_flat_is_zero():
    """Grubhub detail keeps its real availability fee only in the schedule
    while the flat field stays 0 — reconciliation must not zero it out."""
    from app.models.food import FeeSchedule

    feed_row = _pr(Platform.GRUBHUB, rid="g", delivery_fee=0.0)
    agg = AggregatorService.__new__(AggregatorService)

    class FakeScraper:
        async def get_restaurant(self, rid, location, mode):
            detail = _pr(
                Platform.GRUBHUB, rid=rid,
                menu=[MenuItem(name="m", price=1.0)],
                delivery_fee=0.0,
            )
            detail.fee_schedule = FeeSchedule(delivery_fee=3.49, service_fee_pct=12.5)
            return detail

    agg.scrapers = {Platform.GRUBHUB: FakeScraper()}
    aggregated = [_build_aggregated("X", "19713", [feed_row])]
    await agg._enrich_menus(aggregated, "19713")
    p = aggregated[0].platforms[0]
    assert p.fee_schedule.delivery_fee == 3.49  # schedule knows better; kept


# ---------- mode plumbing ----------


@pytest.mark.asyncio
async def test_aggregator_search_passes_mode_to_scrapers():
    received = {}

    class CaptureScraper:
        PLATFORM_NAME = "ue"

        async def _safe_search(self, q, loc, mode):
            received["mode"] = mode
            return []

        async def get_restaurant(self, rid, loc, mode):
            return None

    agg = AggregatorService.__new__(AggregatorService)
    agg.scrapers = {Platform.UBER_EATS: CaptureScraper()}
    out = await agg.search("taco bell", "19713", mode="pickup")
    assert received == {"mode": "pickup"}
    assert out == []


@pytest.mark.asyncio
async def test_aggregator_search_default_mode_is_delivery():
    received = {}

    class CaptureScraper:
        PLATFORM_NAME = "ue"

        async def _safe_search(self, q, loc, mode):
            received["mode"] = mode
            return []

        async def get_restaurant(self, rid, loc, mode):
            return None

    agg = AggregatorService.__new__(AggregatorService)
    agg.scrapers = {Platform.UBER_EATS: CaptureScraper()}
    await agg.search("taco bell", "19713")
    assert received["mode"] == "delivery"
