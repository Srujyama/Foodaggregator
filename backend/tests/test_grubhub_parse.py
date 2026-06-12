"""Tests for app.services.grubhub parsing helpers — phone normalization,
the cents-based fee/minimum parsing, and query-token name matching (all
were live-data bugs)."""

from app.services.grubhub import _normalize_phone, _parse_restaurant, _name_matches_query, _query_tokens


# ---------- phone normalization ----------


def test_normalize_phone_passthrough_string():
    assert _normalize_phone("3024549938") == "3024549938"


def test_normalize_phone_dict_with_country_code():
    # The shape that previously crashed pydantic validation (dict -> str).
    assert _normalize_phone(
        {"country_code": "1", "phone_number": "3024549938"}
    ) == "+1 3024549938"


def test_normalize_phone_none_and_empty():
    assert _normalize_phone(None) is None
    assert _normalize_phone({}) is None
    assert _normalize_phone("") is None


# ---------- cents-based fee / minimum parsing ----------


def test_delivery_fee_parsed_as_cents():
    rd = _parse_restaurant({
        "name": "Tico's Tacos",
        "restaurant_id": "123",
        "delivery_fee": {"price": 300, "currency": "USD"},
    })
    assert rd["delivery_fee"] == 3.00  # not $300


def test_free_delivery_stays_zero():
    rd = _parse_restaurant({
        "name": "X",
        "restaurant_id": "1",
        "delivery_fee": {"price": 0, "currency": "USD"},
    })
    assert rd["delivery_fee"] == 0.0


def test_minimum_order_parsed_as_cents():
    rd = _parse_restaurant({
        "name": "Tico's Tacos",
        "restaurant_id": "123",
        "delivery_minimum": {"price": 2000, "currency": "USD"},
    })
    assert rd["minimum_order"] == 20.00  # not $2000


# ---------- query-token name matching ----------


def test_name_match_survives_apostrophes_in_name():
    """Live bug: searching "mcdonalds" wiped Grubhub's only hit because the
    alpha-only token never substring-matched the apostrophized "McDonald's",
    so the scraper fell back to a web scrape that found nothing."""
    assert _name_matches_query("McDonald's® (815 South College Ave)", _query_tokens("mcdonalds"))
    assert _name_matches_query("Wendy's", _query_tokens("wendys"))
    assert _name_matches_query("Chili's Grill & Bar", _query_tokens("chilis"))


def test_name_match_still_requires_all_tokens():
    assert not _name_matches_query("Burger King", _query_tokens("mcdonalds"))
    assert _name_matches_query("Taco Bell Cantina", _query_tokens("taco bell"))
    assert not _name_matches_query("Taco Loco", _query_tokens("taco bell"))
