"""Parser tests for app.services.uber_shared.

The fixtures are real captures of the public Uber Eats API. They are large but
they exercise the full shape diversity the parser has to handle, so the tests
fail loudly if the response evolves or the parser regresses.
"""

import pytest

from app.models.food import Platform
from app.services.uber_shared import (
    cents_to_dollars,
    parse_fee_string,
    parse_feed,
    parse_feed_store,
    parse_store_detail,
)


# ---------- helpers ----------


def test_parse_fee_string_basic():
    assert parse_fee_string("$2.99 Delivery Fee") == 2.99
    assert parse_fee_string("Free") == 0.0
    assert parse_fee_string("free delivery") == 0.0
    assert parse_fee_string("$0") == 0.0
    assert parse_fee_string("") == 0.0
    assert parse_fee_string(None) == 0.0


def test_parse_fee_string_keeps_value_when_free_word_misleading():
    # "Get $2 off" - the dollar amount is real even though the marketing has 'off'.
    assert parse_fee_string("Get $2 off") == 2.0


def test_cents_to_dollars():
    assert cents_to_dollars(599) == 5.99
    assert cents_to_dollars(0) == 0.0
    assert cents_to_dollars(None) == 0.0
    assert cents_to_dollars("not-a-number") == 0.0
    # Sub-100 with decimals = already dollars
    assert cents_to_dollars(2.99) == 2.99
    # Large round-number ints look like cents
    assert cents_to_dollars(1000) == 10.0


# ---------- parse_feed ----------


def test_parse_feed_returns_results(uber_feed_19713):
    results = parse_feed(uber_feed_19713, Platform.UBER_EATS, "https://www.ubereats.com")
    assert len(results) > 0, "expected at least one parsed store from the captured feed"


def test_parse_feed_extracts_eta_range(uber_feed_19713):
    """The captured feed has stores with 'Delivered in X to Y min' accessibilityText.
    parse_feed should resolve to (eta_min, eta_max) where max >= min."""
    results = parse_feed(uber_feed_19713, Platform.UBER_EATS, "https://www.ubereats.com")
    with_range = [
        r for r in results
        if r.estimated_delivery_minutes_max is not None
        and r.estimated_delivery_minutes_max >= r.estimated_delivery_minutes
    ]
    assert with_range, "expected at least one store with a real ETA range"
    for r in with_range:
        assert r.estimated_delivery_minutes >= 1
        assert r.estimated_delivery_minutes_max >= r.estimated_delivery_minutes


def test_parse_feed_min_le_max_invariant(uber_feed_19713):
    """The parser must never return an inverted range like 30-10."""
    results = parse_feed(uber_feed_19713, Platform.UBER_EATS, "https://www.ubereats.com")
    for r in results:
        if r.estimated_delivery_minutes_max is not None:
            assert r.estimated_delivery_minutes <= r.estimated_delivery_minutes_max, (
                f"inverted range for {r.restaurant_name!r}: "
                f"{r.estimated_delivery_minutes} > {r.estimated_delivery_minutes_max}"
            )


def test_parse_feed_extracts_status_for_unavailable_stores(uber_feed_19713):
    """At least some captured stores were marked NOT_ACCEPTING_ORDERS - those
    should surface as accepting_orders=False with a status_text."""
    results = parse_feed(uber_feed_19713, Platform.UBER_EATS, "https://www.ubereats.com")
    closed = [r for r in results if r.accepting_orders is False]
    assert closed, "fixture is expected to contain at least one closed store"
    for r in closed:
        assert r.status_text, f"closed store {r.restaurant_name!r} missing status_text"


def test_parse_feed_promo_from_signposts(uber_feed_19713):
    results = parse_feed(uber_feed_19713, Platform.UBER_EATS, "https://www.ubereats.com")
    with_promo = [r for r in results if r.promo_text]
    assert with_promo, "fixture has signposts on multiple stores; expected at least one promo"


def test_parse_feed_skips_pickup_only_in_delivery_mode():
    store = {
        "storeUuid": "x",
        "title": {"text": "Test"},
        "actionUrl": "/store/test?diningMode=PICKUP",
        "meta": [{"badgeType": "ETD", "text": "10 min", "accessibilityText": "Delivered in 10 to 15 min"}],
    }
    feed = {"data": {"feedItems": [{"type": "REGULAR_STORE", "store": store}]}}
    delivery = parse_feed(feed, Platform.UBER_EATS, "https://x", accept_pickup=False)
    pickup = parse_feed(feed, Platform.UBER_EATS, "https://x", accept_pickup=True)
    assert delivery == []
    assert len(pickup) == 1


def test_parse_feed_signpost_implies_free_delivery_when_no_FARE_badge():
    """Recent Uber feeds drop the FARE badge and only ship a signpost like
    'Free delivery'. The parser should infer delivery_fee=0 in that case."""
    store = {
        "storeUuid": "x",
        "title": {"text": "Free Test"},
        "actionUrl": "/store/free",
        "meta": [{"badgeType": "ETD", "accessibilityText": "Delivered in 12 to 24 min"}],
        "signposts": [{"text": "Free delivery"}],
    }
    feed = {"data": {"feedItems": [{"type": "REGULAR_STORE", "store": store}]}}
    [r] = parse_feed(feed, Platform.UBER_EATS, "https://x")
    assert r.delivery_fee == 0.0
    assert r.promo_text == "Free delivery"
    assert r.estimated_delivery_minutes == 12
    assert r.estimated_delivery_minutes_max == 24


def test_parse_feed_signpost_dollar_fee_inferred():
    store = {
        "storeUuid": "x",
        "title": {"text": "Two Bucks"},
        "actionUrl": "/store/two",
        "meta": [{"badgeType": "ETD", "accessibilityText": "Delivered in 20 to 30 min"}],
        "signposts": [{"text": "$2.99 Delivery Fee"}],
    }
    feed = {"data": {"feedItems": [{"type": "REGULAR_STORE", "store": store}]}}
    [r] = parse_feed(feed, Platform.UBER_EATS, "https://x")
    assert r.delivery_fee == 2.99


def test_parse_feed_drops_dead_listings():
    """No fare, no eta, no rating -> dropped."""
    store = {"storeUuid": "x", "title": {"text": "Dead"}, "actionUrl": "/", "meta": []}
    feed = {"data": {"feedItems": [{"type": "REGULAR_STORE", "store": store}]}}
    assert parse_feed(feed, Platform.UBER_EATS, "https://x") == []


def test_parse_feed_handles_string_title():
    """Some payload variants ship `title` as a bare string, not a dict."""
    store = {
        "storeUuid": "x",
        "title": "String Title",
        "actionUrl": "/",
        "meta": [{"badgeType": "ETD", "text": "12 min"}],
    }
    feed = {"data": {"feedItems": [{"type": "REGULAR_STORE", "store": store}]}}
    [r] = parse_feed(feed, Platform.UBER_EATS, "https://x")
    assert r.restaurant_name == "String Title"


def test_parse_feed_carousel_item_type_supported():
    store = {
        "storeUuid": "x",
        "title": {"text": "Carousel"},
        "actionUrl": "/",
        "meta": [{"badgeType": "ETD", "text": "12 min"}],
    }
    feed = {"data": {"feedItems": [{"type": "CAROUSEL_V2", "store": store}]}}
    assert len(parse_feed(feed, Platform.UBER_EATS, "https://x")) == 1


def test_parse_feed_store_returns_none_for_missing_id_or_title():
    assert parse_feed_store({"title": {"text": "x"}}, Platform.UBER_EATS, "https://x") is None
    assert parse_feed_store({"storeUuid": "x"}, Platform.UBER_EATS, "https://x") is None


def test_parse_feed_eta_text_unavailable_drops_store():
    store = {
        "storeUuid": "x",
        "title": {"text": "Closed"},
        "actionUrl": "/",
        "meta": [{"badgeType": "ETD", "accessibilityText": "Currently unavailable"}],
        "rating": {"text": "4.0"},
    }
    feed = {"data": {"feedItems": [{"type": "REGULAR_STORE", "store": store}]}}
    assert parse_feed(feed, Platform.UBER_EATS, "https://x") == []


# ---------- parse_store_detail ----------


def test_parse_store_detail_taco_bell_full(uber_store_tacobell):
    res = parse_store_detail(
        uber_store_tacobell,
        "8609aa45-98fb-4268-affc-8da5d0782373",
        Platform.UBER_EATS,
        "https://www.ubereats.com",
    )
    assert res is not None
    assert "Taco Bell" in res.restaurant_name

    # Address should contain the street and the ZIP.
    assert res.address is not None
    assert "Newark" in res.address
    assert "19713" in res.address

    # Phone is a real US number.
    assert res.phone and res.phone.startswith("+1")

    # Categories list is non-empty and pricetag was filtered out.
    assert res.categories
    assert "$" not in res.categories
    assert any(c.lower() in ("mexican", "burritos", "fast food", "tacos") for c in res.categories)

    # priceBucket survives.
    assert res.price_bucket == "$"

    # Hours line was synthesized.
    assert res.hours_today_text and "Open until" in res.hours_today_text

    # Allergen disclaimer carried over as HTML.
    assert res.allergen_disclaimer_html
    assert "<span>" in res.allergen_disclaimer_html.lower() or "<a" in res.allergen_disclaimer_html.lower()

    # Menu items got pulled out and have positive prices.
    assert res.menu_items
    assert all(m.price > 0 for m in res.menu_items)

    # ETA min <= max invariant
    if res.estimated_delivery_minutes_max is not None:
        assert res.estimated_delivery_minutes <= res.estimated_delivery_minutes_max


def test_parse_store_detail_handles_empty_payload():
    assert parse_store_detail({}, "x", Platform.UBER_EATS, "https://x") is None
    assert parse_store_detail({"data": {}}, "x", Platform.UBER_EATS, "https://x") is None
